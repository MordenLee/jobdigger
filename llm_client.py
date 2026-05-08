import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests


@dataclass
class LLMConfig:
    url: str
    model: str
    api_key: str
    timeout: int = 120


class LLMClient:
    def __init__(self, config: LLMConfig):
        self.config = config

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

    def _build_chat_url(self) -> str:
        raw = (self.config.url or "").strip()
        if not raw:
            raise ValueError("llm_url 不能为空")

        parsed = urlparse(raw)
        path = (parsed.path or "").strip()

        if path.endswith("/chat/completions"):
            return raw
        if path in ("", "/"):
            return raw.rstrip("/") + "/v1/chat/completions"
        if path.endswith("/v1"):
            return raw.rstrip("/") + "/chat/completions"
        return raw

    def _extract_json(self, text: str) -> Any:
        text = (text or "").strip()
        if not text:
            raise ValueError("模型返回为空")

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", text)
        if not match:
            raise ValueError(f"无法从模型返回中提取 JSON: {text[:200]}")
        return json.loads(match.group(0))

    def chat_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> Any:
        url = self._build_chat_url()
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }

        resp = requests.post(
            url,
            headers=self._headers(),
            json=payload,
            timeout=self.config.timeout,
        )

        if resp.status_code >= 400:
            fallback_payload = dict(payload)
            fallback_payload.pop("response_format", None)
            resp = requests.post(
                url,
                headers=self._headers(),
                json=fallback_payload,
                timeout=self.config.timeout,
            )

        if resp.status_code >= 400:
            msg = (resp.text or "")[:300]
            raise requests.HTTPError(
                f"LLM 请求失败: HTTP {resp.status_code}, url={url}, body={msg}",
                response=resp,
            )

        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return self._extract_json(content)

    def gen_keywords(self, resume_text: str, limit: int = 6) -> List[str]:
        sys_prompt = "你是招聘搜索词专家，只输出 JSON。"
        user_prompt = (
            "根据简历生成职位搜索关键词，兼顾岗位名称和方向，不要太泛。搜索关键词建议部分英文部分中文。"
            f"最多 {limit} 个，去重。\n"
            "输出格式: {\"keywords\": [\"...\"]}\n"
            f"简历:\n{resume_text[:8000]}"
        )
        data = self.chat_json(sys_prompt, user_prompt, temperature=0.1)
        keywords = data.get("keywords", []) if isinstance(data, dict) else []
        keywords = [str(k).strip() for k in keywords if str(k).strip()]
        return list(dict.fromkeys(keywords))[:limit]

    def score_job(self, resume_text: str, job: Dict[str, Any]) -> Dict[str, Any]:
        sys_prompt = "你是职业规划顾问，只输出 JSON。"
        user_prompt = (
            "1.请评估岗位与候选人的匹配性和性价比相关维度。\n"
            "2.对于兼职、实习外包、限制应届、猎头招聘公司带“某”类的岗位，企业分请直接给到0分，理由写明岗位性质。\n"
            "3.对于大公司、知名企业企业分可以给到80分以上，理由写明公司名气，小公司给到80-60分\n"
            "4.对于互联网行业，工作强度给到40以下，外企给到80以上，国企事业单位给到60-70分，其他行业给到70-80分。\n"
            "根据以上内容输出 JSON 字段:"
            "match_score(0-100), company_score(0-100), workload_score(0-100), reason(<=120字)。\n"
            "workload_score 含义: 分数越高说明工作强度越合理。\n"
            f"候选人简历:\n{resume_text[:6000]}\n\n"
            f"岗位信息:\n{json.dumps(job, ensure_ascii=False)[:6000]}"
        )
        data = self.chat_json(sys_prompt, user_prompt, temperature=0.2)
        if not isinstance(data, dict):
            raise ValueError("模型评分返回格式错误")
        return data
