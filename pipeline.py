import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple
from urllib.parse import urlsplit, urlunsplit

from .constants import DEFAULT_OUTPUT_FILE, DEFAULT_REPORT_FILE, DEFAULT_TARGET_JOBS
from .extract_51job import collect_jobs_by_keyword as collect_51_by_keyword
from .extract_51job import create_browser as create_51_browser
from .extract_51job import open_for_login as open_51_for_login
from .extract_boss import collect_jobs_by_keyword as collect_boss_by_keyword
from .extract_boss import create_browser as create_boss_browser
from .extract_boss import open_for_login as open_boss_for_login
from .extract_boss import save_jobs_json
from .extract_liepin import collect_jobs_by_keyword as collect_liepin_by_keyword
from .extract_liepin import create_browser as create_liepin_browser
from .extract_liepin import open_for_login as open_liepin_for_login
from .extract_shenxianwaiqi import collect_jobs_by_keyword as collect_waiqi_by_keyword
from .extract_shenxianwaiqi import create_browser as create_waiqi_browser
from .extract_shenxianwaiqi import open_for_login as open_waiqi_for_login
from .extract_shenxianwaiqi import select_city as waiqi_select_city
from .extract_zhilian import collect_jobs_by_keyword as collect_zhilian_by_keyword
from .extract_zhilian import create_browser as create_zhilian_browser
from .extract_zhilian import open_for_login as open_zhilian_for_login
from .llm_client import LLMClient, LLMConfig
from .report import generate_html_report
from .resume_loader import load_resume_text


@dataclass
class PipelineInput:
    resume_path: str
    llm_url: str
    model_name: str
    api_key: str
    output_file: str = DEFAULT_OUTPUT_FILE
    report_file: str = DEFAULT_REPORT_FILE
    report_top_n: int = 50
    target_jobs: int = DEFAULT_TARGET_JOBS
    keyword_limit: int = 6
    score_workers: int = 4
    headless: bool = False
    max_pages_per_keyword: int = 2
    city: str = "成都"
    self_education: str = ""

    enable_boss: bool = True
    enable_zhilian: bool = True
    enable_liepin: bool = False
    enable_waiqi: bool = True
    enable_51job: bool = False
    score_keywords: Dict[str, List[str]] = field(default_factory=dict)


EDU_LEVEL = {
    "中专": 1,
    "高中": 1,
    "大专": 2,
    "专科": 2,
    "本科": 3,
    "硕士": 4,
    "博士": 5,
}

BLOCK_WORDS = ["外包", "驻场", "培训生", "代招"]
FIVE_DISTRICTS = ["锦江", "青羊", "金牛", "武侯", "成华"]
SECOND_RING = ["温江", "郫都", "郫县", "双流", "龙泉驿", "新都", "青白江"]

SKILL_VOCAB = [
    "python", "sql", "sas", "r", "excel", "vba", "tableau", "powerbi", "finebi", "bi",
    "pandas", "numpy", "spark", "hadoop", "hive", "flink", "kafka", "etl", "airflow",
    "机器学习", "深度学习", "数据分析", "数据治理", "数据挖掘", "统计建模", "a/b", "abtest",
    "用户增长", "运营分析", "商业分析", "临床数据分析", "cdisc", "ad am", "sdtm",
]

BUSINESS_VOCAB = [
    "医药", "生物", "临床", "金融", "保险", "电商", "零售", "物流", "供应链", "制造",
    "教育", "消费", "快消", "汽车", "互联网", "游戏", "政务", "能源", "地产", "to b",
]

DEFAULT_SCORE_KEYWORDS = {
    "company_platform": ["外企", "外商", "国企", "央企", "上市", "头部", "龙头", "合资"],
    "commute_distance": ["锦江", "青羊", "金牛", "武侯", "成华", "高新区", "天府新区"],
    "experience_requirement": ["1-3年", "3-5年", "经验不限", "可放宽"],
    "core_match": ["sql", "python", "数据分析", "数据治理", "运营分析", "看板"],
}


def _normalize_score_keywords(raw: Any) -> Dict[str, List[str]]:
    if not isinstance(raw, dict):
        return {}
    normalized: Dict[str, List[str]] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        if not isinstance(value, list):
            continue
        items = [str(v).strip() for v in value if str(v).strip()]
        if items:
            normalized[key] = items
    return normalized


def _keywords_for(config: PipelineInput, key: str) -> List[str]:
    if key in config.score_keywords and config.score_keywords[key]:
        return config.score_keywords[key]
    return DEFAULT_SCORE_KEYWORDS.get(key, [])


def _keyword_ratio_score(text: str, keywords: List[str], max_score: float) -> float:
    cleaned = [k.strip().lower() for k in (keywords or []) if str(k).strip()]
    if not cleaned:
        return 0.0
    t = (text or "").lower()
    hits = sum(1 for k in cleaned if k in t)
    return round(min(max_score, max_score * hits / len(cleaned)), 2)


def _contains_excluded_word(job: Dict[str, Any]) -> bool:
    text_parts = [
        str(job.get("job_name", "")),
        str(job.get("salary", "")),
        str(job.get("jd_description", "")),
        " ".join(job.get("tags", []) or []),
        " ".join(job.get("jd_labels", []) or []),
    ]
    txt = " ".join(text_parts)

    if "兼职" in txt:
        return True
    if "实习" in txt:
        return True
    if "/" in str(job.get("salary", "")):
        return True
    return False


def _infer_resume_education(text: str) -> str:
    t = (text or "")
    for k in ["博士", "硕士", "本科", "大专", "专科", "高中", "中专"]:
        if k in t:
            return "大专" if k == "专科" else k
    return ""


def _edu_level(edu: str) -> int:
    s = (edu or "").strip()
    if not s:
        return 0
    for k, v in EDU_LEVEL.items():
        if k in s:
            return v
    return 0


def _job_required_education(job: Dict[str, Any]) -> str:
    cands = [
        str(job.get("education", "")),
        str(job.get("detail_education", "")),
        str(job.get("job_degree", "")),
        str(job.get("base_info", "")),
        str(job.get("jd_description", ""))[:300],
    ]
    text = " ".join(cands)
    for k in ["博士", "硕士", "本科", "大专", "专科", "高中", "中专"]:
        if k in text:
            return "大专" if k == "专科" else k
    return ""


def _extract_tokens(text: str, vocab: List[str]) -> set:
    t = (text or "").lower().replace("/", " ").replace("-", " ")
    found = set()
    for token in vocab:
        if token.lower() in t:
            found.add(token.lower())
    return found


def _city_ok(job: Dict[str, Any], target_city: str) -> bool:
    city = (target_city or "").strip()
    if not city:
        return True

    text = " ".join(
        [
            str(job.get("city", "")),
            str(job.get("location", "")),
            str(job.get("detail_city_area", "")),
            str(job.get("work_address", "")),
            str(job.get("area", "")),
        ]
    )
    return city in text


def _contains_block_words(job: Dict[str, Any]) -> bool:
    text = " ".join([str(job.get("job_name", "")), str(job.get("jd_description", ""))])
    return any(w in text for w in BLOCK_WORDS)


def _company_nature_score(job: Dict[str, Any], company_keywords: List[str]) -> float:
    text = " ".join(
        [
            str(job.get("company", "")),
            " ".join(job.get("company_tags", []) or []),
            " ".join(job.get("company_props", []) or []),
            " ".join(job.get("detail_company_meta", []) or []),
            str(job.get("company_intro", ""))[:500],
        ]
    )

    configured = _keyword_ratio_score(text, company_keywords, 20.0)
    if configured > 0:
        return configured

    if any(k in text for k in ["外企", "外商", "知名国企", "央企"]):
        return 20.0
    if any(k in text for k in ["国企", "事业单位", "编制"]):
        return 15.0
    if any(k in text for k in ["合资", "上市", "头部", "龙头"]):
        return 10.0
    if any(k in text for k in ["民营", "互联网", "私企"]):
        return 5.0
    if any(k in text for k in ["a轮", "天使轮", "初创", "20人以下"]):
        return 0.0
    return 5.0


def _commute_score(job: Dict[str, Any], commute_keywords: List[str]) -> float:
    text = " ".join(
        [
            str(job.get("location", "")),
            str(job.get("detail_city_area", "")),
            str(job.get("work_address", "")),
            str(job.get("area", "")),
        ]
    )
    configured = _keyword_ratio_score(text, commute_keywords, 15.0)
    if configured > 0:
        return configured

    if any(d in text for d in FIVE_DISTRICTS):
        return 15.0
    if any(d in text for d in SECOND_RING):
        return 10.0
    if "成都" in text:
        return 5.0
    return 0.0


def _experience_score(job: Dict[str, Any], experience_keywords: List[str]) -> float:
    text = " ".join(
        [
            str(job.get("experience", "")),
            str(job.get("detail_experience", "")),
            str(job.get("job_year", "")),
            str(job.get("base_info", "")),
        ]
    )
    configured = _keyword_ratio_score(text, experience_keywords, 15.0)
    if configured > 0:
        return configured

    if re.search(r"1\s*[-~到]\s*3年|1-3年", text):
        return 15.0
    if re.search(r"3\s*[-~到]\s*5年|3-5年", text):
        return 10.0
    if re.search(r"5\s*年以上|5\s*[-~到]\s*10年|5-10年", text):
        return 5.0
    if "经验不限" in text:
        return 10.0
    return 8.0


def _core_skill_score(
    job: Dict[str, Any],
    resume_text: str,
    resume_skill_tokens: set,
    resume_business_tokens: set,
    core_keywords: List[str],
) -> Dict[str, float]:
    jd_text = " ".join(
        [
            str(job.get("job_name", "")),
            str(job.get("jd_description", "")),
            " ".join(job.get("tags", []) or []),
            " ".join(job.get("jd_labels", []) or []),
            " ".join(job.get("jd_skills", []) or []),
        ]
    )

    configured = [k.strip().lower() for k in (core_keywords or []) if str(k).strip()]
    if configured:
        jd_lower = jd_text.lower()
        resume_lower = (resume_text or "").lower()
        shared_hits = [k for k in configured if k in jd_lower and k in resume_lower]
        ratio = len(shared_hits) / len(configured)
        skill_score = min(35.0, 35.0 * ratio)
        business_score = min(10.0, 10.0 * ratio)
        bonus_score = 5.0 if ratio >= 0.6 else 0.0
        return {
            "skill_stack_score": round(skill_score, 2),
            "business_score": round(business_score, 2),
            "bonus_score": round(bonus_score, 2),
        }

    jd_skill_tokens = _extract_tokens(jd_text, SKILL_VOCAB)
    jd_business_tokens = _extract_tokens(jd_text, BUSINESS_VOCAB)

    skill_overlap = jd_skill_tokens & resume_skill_tokens
    business_overlap = jd_business_tokens & resume_business_tokens

    if jd_skill_tokens:
        skill_score = 35.0 * len(skill_overlap) / len(jd_skill_tokens)
    else:
        skill_score = 20.0

    if jd_business_tokens:
        business_score = 10.0 if business_overlap else 0.0
    else:
        business_score = 5.0

    bonus_score = 5.0 if ("优先" in jd_text and (skill_overlap or business_overlap)) else 0.0

    return {
        "skill_stack_score": round(min(35.0, skill_score), 2),
        "business_score": round(min(10.0, business_score), 2),
        "bonus_score": round(min(5.0, bonus_score), 2),
    }


def _fallback_keywords(resume_text: str) -> List[str]:
    defaults = ["数据分析", "数据运营", "商业分析", "产品经理", "算法工程师", "项目经理"]
    if "python" in resume_text.lower() or "数据" in resume_text:
        return defaults
    return ["运营", "销售", "行政", "项目管理", "客户成功"]


def _normalize_job_url(url: str) -> str:
    s = (url or "").strip()
    if not s:
        return ""
    try:
        parts = urlsplit(s)
        clean = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))
        return clean
    except Exception:
        return s


def _job_dedupe_keys(job: Dict[str, Any]) -> List[str]:
    keys: List[str] = []

    job_id = str(job.get("job_id", "")).strip().lower()
    if job_id:
        keys.append(f"id:{job_id}")

    job_url = _normalize_job_url(str(job.get("job_url", "")))
    if job_url:
        keys.append(f"url:{job_url}")

    name = str(job.get("job_name", "")).strip().lower()
    company = str(job.get("company", "")).strip().lower()
    if name and company:
        keys.append(f"nc:{name}|{company}")

    return keys


def _dedupe_jobs_with_stats(jobs: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    unique: List[Dict[str, Any]] = []
    seen_keys = set()
    stats = {
        "input": len(jobs),
        "kept": 0,
        "duplicates": 0,
        "duplicate_by_id": 0,
        "duplicate_by_url": 0,
        "duplicate_by_name_company": 0,
    }

    for job in jobs:
        keys = _job_dedupe_keys(job)
        matched_types = set()
        for k in keys:
            if k in seen_keys:
                if k.startswith("id:"):
                    matched_types.add("id")
                elif k.startswith("url:"):
                    matched_types.add("url")
                elif k.startswith("nc:"):
                    matched_types.add("nc")

        if matched_types:
            stats["duplicates"] += 1
            if "id" in matched_types:
                stats["duplicate_by_id"] += 1
            if "url" in matched_types:
                stats["duplicate_by_url"] += 1
            if "nc" in matched_types:
                stats["duplicate_by_name_company"] += 1
            continue

        unique.append(job)
        stats["kept"] += 1
        for k in keys:
            seen_keys.add(k)

    return unique, stats


def _dedupe_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique, _ = _dedupe_jobs_with_stats(jobs)
    return unique


def _save_raw_jobs(jobs: List[Dict[str, Any]], path: str) -> None:
    """将原始抓取结果增量写入磁盘，供程序中断时恢复用。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(jobs, f, ensure_ascii=False, indent=2)
    except Exception as ex:
        print(f"警告: 原始数据保存失败: {ex}")


def _collect_near_200_jobs(config: PipelineInput, llm: LLMClient, resume_text: str) -> List[Dict[str, Any]]:
    try:
        keywords = llm.gen_keywords(resume_text, limit=config.keyword_limit)
    except Exception as ex:
        print(f"警告: 关键词生成失败，将使用兜底关键词。原因: {ex}")
        keywords = []
    if not keywords:
        keywords = _fallback_keywords(resume_text)

    print(f"关键词: {keywords}")

    all_jobs: List[Dict[str, Any]] = []
    seen_keys = set()
    per_kw = max(30, min(80, config.target_jobs // max(1, len(keywords)) + 10))
    collect_stats = {
        "keyword_total": 0,
        "fetched": 0,
        "duplicates": 0,
        "duplicate_by_id": 0,
        "duplicate_by_url": 0,
        "duplicate_by_name_company": 0,
        "kept": 0,
    }

    sources = []
    if config.enable_boss:
        sources.append(
            {
                "name": "boss",
                "create": create_boss_browser,
                "login": open_boss_for_login,
                "collect": lambda p, k, mj, mp: collect_boss_by_keyword(p, k, max_jobs=mj, max_scroll_rounds=max(8, mp * 5)),
            }
        )
    if config.enable_zhilian:
        sources.append(
            {
                "name": "zhilian",
                "create": create_zhilian_browser,
                "login": open_zhilian_for_login,
                "collect": lambda p, k, mj, mp: collect_zhilian_by_keyword(p, k, max_jobs=mj, max_pages=mp),
            }
        )
    if config.enable_liepin:
        sources.append(
            {
                "name": "liepin",
                "create": create_liepin_browser,
                "login": open_liepin_for_login,
                "collect": lambda p, k, mj, mp: collect_liepin_by_keyword(p, k, max_jobs=mj, max_pages=mp),
            }
        )
    if config.enable_waiqi:
        sources.append(
            {
                "name": "waiqi",
                "create": create_waiqi_browser,
                "login": lambda p: (open_waiqi_for_login(p), waiqi_select_city(p, config.city)),
                "collect": lambda p, k, mj, mp: collect_waiqi_by_keyword(p, k, max_jobs=mj, max_pages=mp),
            }
        )
    if config.enable_51job:
        sources.append(
            {
                "name": "51job",
                "create": create_51_browser,
                "login": lambda p: open_51_for_login(p, config.city),
                "collect": lambda p, k, mj, mp: collect_51_by_keyword(p, k, max_jobs=max(20, mj // 2), max_pages=mp),
            }
        )

    if not sources:
        raise ValueError("未启用任何招聘站点，请在配置中开启至少一个来源。")

    source_count = len(sources)
    base_quota = config.target_jobs // source_count
    remainder = config.target_jobs % source_count

    for source_idx, source in enumerate(sources):
        # 按站点分配采集配额，避免首个站点抓满后后续站点完全不执行。
        source_quota = base_quota + (1 if source_idx < remainder else 0)
        source_start_kept = collect_stats["kept"]

        page = source["create"](headless=config.headless)
        try:
            print(f"\n=== 准备登录站点: {source['name']} ===")
            source["login"](page)

            for idx, kw in enumerate(keywords, start=1):
                if len(all_jobs) >= config.target_jobs:
                    break

                # 非最后一个站点达到自身配额后，切到下一个站点继续采集。
                if source_idx < source_count - 1:
                    source_kept_now = collect_stats["kept"] - source_start_kept
                    if source_kept_now >= source_quota:
                        print(f"[{source['name']}] 已达到站点配额 {source_quota}，切换下一个站点。")
                        break

                collect_stats["keyword_total"] += 1
                print(f"[{source['name']}] [{idx}/{len(keywords)}] 抓取关键词: {kw}")
                try:
                    jobs = source["collect"](page, kw, per_kw, config.max_pages_per_keyword)
                except Exception as kw_err:
                    print(f"[{source['name']}] 关键词 {kw} 抓取失败，跳过。原因: {kw_err}")
                    jobs = []
                collect_stats["fetched"] += len(jobs)

                for job in jobs:
                    keys = _job_dedupe_keys(job)
                    matched_types = set()
                    for k in keys:
                        if k in seen_keys:
                            if k.startswith("id:"):
                                matched_types.add("id")
                            elif k.startswith("url:"):
                                matched_types.add("url")
                            elif k.startswith("nc:"):
                                matched_types.add("nc")

                    if matched_types:
                        collect_stats["duplicates"] += 1
                        if "id" in matched_types:
                            collect_stats["duplicate_by_id"] += 1
                        if "url" in matched_types:
                            collect_stats["duplicate_by_url"] += 1
                        if "nc" in matched_types:
                            collect_stats["duplicate_by_name_company"] += 1
                        continue

                    all_jobs.append(job)
                    collect_stats["kept"] += 1
                    for k in keys:
                        seen_keys.add(k)

                print(
                    f"[{source['name']}] 关键词 {kw} 完成: 抓取={len(jobs)} | "
                    f"累计保留={collect_stats['kept']} | 重复过滤={collect_stats['duplicates']}"
                )

                # 每个关键词完成后增量保存原始数据，防止后续站点崩溃丢失已有数据
                raw_path = config.output_file + ".raw.json"
                _save_raw_jobs(all_jobs, raw_path)
                print(f"[存档] 已保存 {len(all_jobs)} 条原始数据 -> {raw_path}")

                if len(all_jobs) >= config.target_jobs:
                    break

            source_kept_total = collect_stats["kept"] - source_start_kept
            print(
                f"[{source['name']}] 站点采集结束: 站点保留={source_kept_total} / 目标配额={source_quota}"
            )
        finally:
            try:
                page.quit()
            except Exception:
                pass

    print(
        "跨关键词去重统计: "
        f"关键词数={collect_stats['keyword_total']} | "
        f"抓取总数={collect_stats['fetched']} | "
        f"保留={collect_stats['kept']} | "
        f"重复={collect_stats['duplicates']} "
        f"(id={collect_stats['duplicate_by_id']}, "
        f"url={collect_stats['duplicate_by_url']}, "
        f"name_company={collect_stats['duplicate_by_name_company']})"
    )

    all_jobs, post_stats = _dedupe_jobs_with_stats(all_jobs)
    if post_stats["duplicates"] > 0:
        print(
            "抓取后兜底去重统计: "
            f"输入={post_stats['input']} | 保留={post_stats['kept']} | 重复={post_stats['duplicates']} "
            f"(id={post_stats['duplicate_by_id']}, "
            f"url={post_stats['duplicate_by_url']}, "
            f"name_company={post_stats['duplicate_by_name_company']})"
        )
    if len(all_jobs) > config.target_jobs:
        all_jobs = all_jobs[: config.target_jobs]

    return all_jobs


def _score_job(
    resume_text: str,
    resume_edu: str,
    resume_skill_tokens: set,
    resume_business_tokens: set,
    score_keywords: Dict[str, List[str]],
    target_city: str,
    job: Dict[str, Any],
) -> Dict[str, Any]:
    enriched = dict(job)
    enriched["llm_reason"] = ""

    req_edu = _job_required_education(job)
    resume_level = _edu_level(resume_edu)
    req_level = _edu_level(req_edu)

    edu_text = " ".join(
        [
            str(job.get("education", "")),
            str(job.get("detail_education", "")),
            str(job.get("job_degree", "")),
            str(job.get("jd_description", ""))[:300],
        ]
    )

    if req_level > 0 and resume_level < req_level:
        enriched["gate_pass"] = False
        enriched["gate_reason"] = f"学历不满足: 岗位要求{req_edu}，候选人为{resume_edu or '未知'}"
        enriched["value_for_money_score"] = 0.0
        enriched["company_nature_score"] = 0.0
        enriched["commute_score"] = 0.0
        enriched["experience_score"] = 0.0
        enriched["skill_stack_score"] = 0.0
        enriched["business_score"] = 0.0
        enriched["bonus_score"] = 0.0
        return enriched

    if "统招本科" in edu_text and resume_level < EDU_LEVEL["本科"]:
        enriched["gate_pass"] = False
        enriched["gate_reason"] = f"学历不满足统招本科要求，候选人为{resume_edu or '未知'}"
        enriched["value_for_money_score"] = 0.0
        enriched["company_nature_score"] = 0.0
        enriched["commute_score"] = 0.0
        enriched["experience_score"] = 0.0
        enriched["skill_stack_score"] = 0.0
        enriched["business_score"] = 0.0
        enriched["bonus_score"] = 0.0
        return enriched

    if not _city_ok(job, target_city):
        enriched["gate_pass"] = False
        enriched["gate_reason"] = f"岗位城市不匹配: 目标城市={target_city or '未设置'}"
        enriched["value_for_money_score"] = 0.0
        enriched["company_nature_score"] = 0.0
        enriched["commute_score"] = 0.0
        enriched["experience_score"] = 0.0
        enriched["skill_stack_score"] = 0.0
        enriched["business_score"] = 0.0
        enriched["bonus_score"] = 0.0
        return enriched

    if _contains_block_words(job):
        enriched["gate_pass"] = False
        enriched["gate_reason"] = "命中外包/驻场/培训生/代招等风险词"
        enriched["value_for_money_score"] = 0.0
        enriched["company_nature_score"] = 0.0
        enriched["commute_score"] = 0.0
        enriched["experience_score"] = 0.0
        enriched["skill_stack_score"] = 0.0
        enriched["business_score"] = 0.0
        enriched["bonus_score"] = 0.0
        return enriched

    company_score = _company_nature_score(job, score_keywords.get("company_platform", []))
    commute_score = _commute_score(job, score_keywords.get("commute_distance", []))
    exp_score = _experience_score(job, score_keywords.get("experience_requirement", []))
    core = _core_skill_score(
        job,
        resume_text,
        resume_skill_tokens,
        resume_business_tokens,
        score_keywords.get("core_match", []),
    )

    total = company_score + commute_score + exp_score + core["skill_stack_score"] + core["business_score"] + core["bonus_score"]

    enriched["gate_pass"] = True
    enriched["gate_reason"] = ""
    enriched["company_nature_score"] = round(company_score, 2)
    enriched["commute_score"] = round(commute_score, 2)
    enriched["experience_score"] = round(exp_score, 2)
    enriched["skill_stack_score"] = core["skill_stack_score"]
    enriched["business_score"] = core["business_score"]
    enriched["bonus_score"] = core["bonus_score"]
    enriched["value_for_money_score"] = round(min(100.0, total), 2)
    return enriched


def run_pipeline(config: PipelineInput) -> List[Dict[str, Any]]:
    try:
        resume_text = load_resume_text(config.resume_path)
    except ValueError as ex:
        if "简历内容为空" not in str(ex):
            raise
        print(f"警告: {ex}")
        print("将使用兜底简历文本继续执行（关键词与评分可能不如真实简历准确）。")
        resume_text = "候选人未提供可解析的简历内容，请基于通用岗位胜任力进行评估。"
    llm = LLMClient(LLMConfig(url=config.llm_url, model=config.model_name, api_key=config.api_key))

    resume_edu = config.self_education.strip() or _infer_resume_education(resume_text)
    resume_skill_tokens = _extract_tokens(resume_text, SKILL_VOCAB)
    resume_business_tokens = _extract_tokens(resume_text, BUSINESS_VOCAB)
    score_keywords = {
        "company_platform": _keywords_for(config, "company_platform"),
        "commute_distance": _keywords_for(config, "commute_distance"),
        "experience_requirement": _keywords_for(config, "experience_requirement"),
        "core_match": _keywords_for(config, "core_match"),
    }
    print(f"简历学历识别: {resume_edu or '未知'}")
    score_keyword_counts = {k: len(v) for k, v in score_keywords.items()}
    print(f"评分关键词已加载: {score_keyword_counts}")

    raw_jobs = _collect_near_200_jobs(config, llm, resume_text)
    raw_jobs, final_stats = _dedupe_jobs_with_stats(raw_jobs)
    if final_stats["duplicates"] > 0:
        print(
            "评分前最终去重统计: "
            f"输入={final_stats['input']} | 保留={final_stats['kept']} | 重复={final_stats['duplicates']} "
            f"(id={final_stats['duplicate_by_id']}, "
            f"url={final_stats['duplicate_by_url']}, "
            f"name_company={final_stats['duplicate_by_name_company']})"
        )
    print(f"抓取完成，总计: {len(raw_jobs)}")

    filtered_jobs = [j for j in raw_jobs if not _contains_excluded_word(j)]
    print(f"过滤兼职/实习后: {len(filtered_jobs)}")
    print(f"评分并发数: {config.score_workers}")

    scored_jobs: List[Dict[str, Any]] = []
    total = len(filtered_jobs)
    if total > 0:
        worker_count = max(1, min(config.score_workers, total))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                    executor.submit(
                        _score_job,
                        resume_text,
                        resume_edu,
                        resume_skill_tokens,
                        resume_business_tokens,
                        score_keywords,
                        config.city,
                        job,
                    ): (idx, job)
                for idx, job in enumerate(filtered_jobs, start=1)
            }

            done_count = 0
            for future in as_completed(future_map):
                idx, job = future_map[future]
                done_count += 1
                try:
                    scored = future.result()
                    scored["rank"] = idx
                    scored_jobs.append(scored)
                    print(
                        f"评分 {done_count}/{total}: "
                        f"{scored.get('job_name', '')} -> {scored.get('value_for_money_score', 0)}"
                    )
                except Exception as ex:
                    failed = dict(job)
                    failed["score_error"] = str(ex)
                    failed["value_for_money_score"] = 0
                    scored_jobs.append(failed)
                    print(f"评分 {done_count}/{total}: 失败 -> {job.get('job_name', '')}")

    scored_jobs.sort(key=lambda x: x.get("value_for_money_score", 0), reverse=True)

    for i, item in enumerate(scored_jobs, start=1):
        item["rank"] = i

    save_jobs_json(scored_jobs, config.output_file)
    generate_html_report(scored_jobs, config.report_file, top_n=config.report_top_n)

    print("完成。")
    print(f"输出文件: {config.output_file}")
    print(f"报告文件: {config.report_file}")

    return scored_jobs


def run_pipeline_from_dict(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    score_keywords = _normalize_score_keywords(data.get("score_keywords", {}))
    config = PipelineInput(
        resume_path=str(data["resume_path"]),
        llm_url=str(data["llm_url"]),
        model_name=str(data["model_name"]),
        api_key=str(data["api_key"]),
        output_file=str(data.get("output_file", DEFAULT_OUTPUT_FILE)),
        report_file=str(data.get("report_file", DEFAULT_REPORT_FILE)),
        report_top_n=int(data.get("report_top_n", 50)),
        target_jobs=int(data.get("target_jobs", DEFAULT_TARGET_JOBS)),
        keyword_limit=int(data.get("keyword_limit", 6)),
        score_workers=int(data.get("score_workers", 4)),
        headless=bool(data.get("headless", False)),
        max_pages_per_keyword=int(data.get("max_pages_per_keyword", 2)),
        city=str(data.get("city", "成都")),
        self_education=str(data.get("self_education", "")),
        enable_boss=bool(data.get("enable_boss", True)),
        enable_zhilian=bool(data.get("enable_zhilian", True)),
        enable_liepin=bool(data.get("enable_liepin", False)),
        enable_waiqi=bool(data.get("enable_waiqi", True)),
        enable_51job=bool(data.get("enable_51job", False)),
        score_keywords=score_keywords,
    )
    return run_pipeline(config)


def run_from_json_config(config_path: str) -> List[Dict[str, Any]]:
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return run_pipeline_from_dict(data)
