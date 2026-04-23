from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import torch

from app.core.settings import Settings


class VideoVLRunner:
    def __init__(self, settings: Settings, logger) -> None:
        self.settings = settings
        self.logger = logger
        self._processor = None
        self._model = None

    def _json_safe(self, value):
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    def _parse_output_json(self, text: str) -> dict | list | None:
        candidate = text.strip()
        if not candidate:
            return None

        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            candidate = fenced.group(1).strip()

        for body in (candidate,):
            try:
                parsed = json.loads(body)
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                pass

        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                parsed = json.loads(candidate[start : end + 1])
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                return None
        return None

    def _ensure_runtime(self) -> None:
        if self._processor is not None and self._model is not None:
            return

        from transformers import AutoModelForImageTextToText, AutoProcessor

        checkpoint_path = self.settings.video_vl_model_id
        self.logger.info("Loading Qwen3-VL transformers runtime from %s", checkpoint_path)

        model_kwargs = {
            "dtype": "auto",
            "device_map": "auto",
        }
        if self.settings.video_vl_use_flash_attention_2:
            try:
                import flash_attn  # noqa: F401

                model_kwargs["attn_implementation"] = "flash_attention_2"
                self.logger.info("Enabling flash_attention_2 for transformers backend")
            except Exception:
                self.logger.info("flash_attention_2 is unavailable, falling back to default attention")

        self._model = AutoModelForImageTextToText.from_pretrained(checkpoint_path, **model_kwargs)
        self._processor = AutoProcessor.from_pretrained(checkpoint_path)

    def _normalize_message_content(self, content: Any) -> list[dict]:
        if isinstance(content, list):
            normalized: list[dict] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") in {"text", "image", "video"}:
                    normalized.append(item)
                else:
                    normalized.append({"type": "text", "text": str(item)})
            return normalized
        if isinstance(content, str):
            return [{"type": "text", "text": content}]
        return [{"type": "text", "text": str(content)}]

    def _build_messages(self, request: dict, video_path: Path, max_frames: int) -> list[dict]:
        params = request.get("params") or {}
        incoming_messages = request.get("messages") or []
        messages: list[dict] = []
        for item in incoming_messages:
            if not isinstance(item, dict):
                continue
            role = item.get("role", "user")
            messages.append({"role": role, "content": self._normalize_message_content(item.get("content", ""))})

        if not messages:
            messages = [{"role": "user", "content": [{"type": "text", "text": "请分析这个视频。"}]}]

        video_part = {
            "type": "video",
            "video": video_path.as_uri(),
            "fps": params.get("sample_fps", 1.0),
            "max_frames": max_frames,
            "min_pixels": self.settings.video_vl_transformers_min_pixels,
            "max_pixels": self.settings.video_vl_transformers_max_pixels,
            "total_pixels": self.settings.video_vl_transformers_total_pixels,
        }

        user_indexes = [index for index, item in enumerate(messages) if item["role"] == "user"]
        target_index = user_indexes[-1] if user_indexes else len(messages) - 1
        messages[target_index]["content"] = [video_part, *messages[target_index]["content"]]

        response_format = params.get("response_format")
        if isinstance(response_format, dict) and response_format.get("type") == "json_schema":
            schema_text = json.dumps(response_format.get("json_schema"), ensure_ascii=False)
            messages[target_index]["content"].append(
                {
                    "type": "text",
                    "text": f"请严格输出 JSON，并尽量符合以下 schema 定义：{schema_text}",
                }
            )
        return messages

    def _prepare_inputs(self, request: dict) -> tuple[dict, dict]:
        from qwen_vl_utils import process_vision_info

        params = request.get("params") or {}
        video_path = Path(request["file_uri"]).resolve()
        max_frames = min(
            int(params.get("max_frames", self.settings.video_vl_transformers_max_frames)),
            self.settings.video_vl_transformers_max_frames,
        )
        messages = self._build_messages(request, video_path, max_frames)

        text = self._processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        patch_size = getattr(self._processor.image_processor, "patch_size", 16)
        images, videos, video_kwargs = process_vision_info(
            messages,
            image_patch_size=patch_size,
            return_video_kwargs=True,
            return_video_metadata=True,
        )

        if videos is not None:
            videos, video_metadatas = zip(*videos)
            videos, video_metadatas = list(videos), list(video_metadatas)
        else:
            video_metadatas = None

        inputs = self._processor(
            text=text,
            images=images,
            videos=videos,
            video_metadata=video_metadatas,
            return_tensors="pt",
            do_resize=False,
            **video_kwargs,
        )
        inputs = inputs.to(self._model.device)

        metadata = {
            "messages": messages,
            "video_kwargs": video_kwargs,
            "video_metadata": video_metadatas,
            "max_frames": max_frames,
        }
        return inputs, metadata

    def analyze(self, request: dict) -> dict:
        params = request.get("params") or {}
        video_path = Path(request["file_uri"])
        if not video_path.exists():
            raise FileNotFoundError(f"file_uri 不存在: {video_path}")

        self._ensure_runtime()

        inputs, metadata = self._prepare_inputs(request)
        generation = params.get("generation") or {}
        max_new_tokens = int(generation.get("max_output_tokens", self.settings.video_vl_default_max_output_tokens))
        temperature = float(generation.get("temperature", self.settings.video_vl_default_temperature))
        top_p = float(generation.get("top_p", self.settings.video_vl_default_top_p))
        with torch.inference_mode():
            generated_ids = self._model.generate(
                **inputs,
                do_sample=True,
                temperature=temperature,
                top_p=top_p,
                top_k=20,
                repetition_penalty=1.0,
                max_new_tokens=max_new_tokens,
            )

        generated_ids_trimmed = [
            out_ids[len(in_ids) :] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = self._processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
        generated_text = output_text[0] if output_text else ""

        parsed_json = self._parse_output_json(generated_text)

        result = {
            "backend": "transformers",
            "model_id": self.settings.video_vl_model_id,
            "file_uri": str(video_path),
            "profile": params.get("profile", "standard"),
            "language": params.get("language"),
            "messages": metadata["messages"],
            "response_format": params.get("response_format"),
            "max_frames": metadata["max_frames"],
            "sample_fps": params.get("sample_fps", 1.0),
            "video_kwargs": self._json_safe(metadata["video_kwargs"]),
            "video_metadata": self._json_safe(metadata["video_metadata"]),
            "generation": {
                "max_output_tokens": max_new_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "top_k": 20,
                "repetition_penalty": 1.0,
            },
            "output_text": generated_text,
            "output_json": parsed_json,
        }
        return result
