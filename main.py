import argparse
import json

from .constants import DEFAULT_OUTPUT_FILE, DEFAULT_REPORT_FILE, DEFAULT_TARGET_JOBS
from .pipeline import PipelineInput, run_pipeline, run_pipeline_from_dict


def _ask_if_empty(value: str, prompt: str) -> str:
    if value:
        return value
    return input(prompt).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JobMiner MVP")
    parser.add_argument("--config", default="", help="JSON 配置文件路径")
    parser.add_argument("--resume", dest="resume_path", default="", help="简历文件路径")
    parser.add_argument("--llm-url", default="", help="大模型 API URL（OpenAI兼容）")
    parser.add_argument("--model", dest="model_name", default="", help="模型名称")
    parser.add_argument("--api-key", default="", help="API Key")
    parser.add_argument("--output", dest="output_file", default=DEFAULT_OUTPUT_FILE, help="输出 JSON 文件")
    parser.add_argument("--report", dest="report_file", default=DEFAULT_REPORT_FILE, help="输出 HTML 报告文件")
    parser.add_argument("--report-top-n", type=int, default=50, help="HTML 报告展示前 N 条")
    parser.add_argument("--target-jobs", type=int, default=DEFAULT_TARGET_JOBS, help="目标抓取岗位数量")
    parser.add_argument("--keyword-limit", type=int, default=6, help="关键词数量上限")
    parser.add_argument("--score-workers", type=int, default=4, help="模型评分并发数")
    parser.add_argument("--max-pages-per-keyword", type=int, default=2, help="每个关键词每个站点最大翻页数")
    parser.add_argument("--city", default="成都", help="目标城市，默认成都")
    parser.add_argument("--self-education", default="", help="候选人学历（可选，优先于自动识别）")
    parser.add_argument("--enable-51job", action="store_true", help="启用前程无忧抓取（默认关闭）")
    parser.add_argument("--enable-liepin", action="store_true", help="启用猎聘抓取（默认关闭）")
    parser.add_argument("--disable-boss", action="store_true", help="关闭Boss直聘抓取")
    parser.add_argument("--disable-zhilian", action="store_true", help="关闭智联抓取")
    parser.add_argument("--disable-waiqi", action="store_true", help="关闭神仙外企抓取")
    parser.add_argument("--headless", action="store_true", help="无头模式（一般不建议，登录不方便）")
    return parser


def _load_config(config_path: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("配置文件根节点必须是 JSON 对象")
    return data


def _merge_cli_overrides(base: dict, args: argparse.Namespace) -> dict:
    data = dict(base)

    overrides = {
        "resume_path": args.resume_path,
        "llm_url": args.llm_url,
        "model_name": args.model_name,
        "api_key": args.api_key,
    }
    for k, v in overrides.items():
        if v:
            data[k] = v

    if args.output_file != DEFAULT_OUTPUT_FILE:
        data["output_file"] = args.output_file
    if args.report_file != DEFAULT_REPORT_FILE:
        data["report_file"] = args.report_file
    if args.report_top_n != 50:
        data["report_top_n"] = args.report_top_n
    if args.target_jobs != DEFAULT_TARGET_JOBS:
        data["target_jobs"] = args.target_jobs
    if args.keyword_limit != 6:
        data["keyword_limit"] = args.keyword_limit
    if args.score_workers != 4:
        data["score_workers"] = args.score_workers
    if args.max_pages_per_keyword != 2:
        data["max_pages_per_keyword"] = args.max_pages_per_keyword
    if args.city != "成都":
        data["city"] = args.city
    if args.self_education:
        data["self_education"] = args.self_education

    if args.enable_51job:
        data["enable_51job"] = True
    if args.disable_boss:
        data["enable_boss"] = False
    if args.disable_zhilian:
        data["enable_zhilian"] = False
    if args.enable_liepin:
        data["enable_liepin"] = True
    else:
        data["enable_liepin"] = False
    if args.disable_waiqi:
        data["enable_waiqi"] = False

    if args.headless:
        data["headless"] = True

    return data


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.config:
        data = _load_config(args.config)
        merged = _merge_cli_overrides(data, args)
        run_pipeline_from_dict(merged)
        return

    resume_path = _ask_if_empty(args.resume_path, "请输入简历路径: ")
    llm_url = _ask_if_empty(args.llm_url, "请输入大模型 URL: ")
    model_name = _ask_if_empty(args.model_name, "请输入模型名称: ")
    api_key = _ask_if_empty(args.api_key, "请输入 API Key: ")

    config = PipelineInput(
        resume_path=resume_path,
        llm_url=llm_url,
        model_name=model_name,
        api_key=api_key,
        output_file=args.output_file,
        report_file=args.report_file,
        report_top_n=args.report_top_n,
        target_jobs=args.target_jobs,
        keyword_limit=args.keyword_limit,
        score_workers=args.score_workers,
        max_pages_per_keyword=args.max_pages_per_keyword,
        city=args.city,
        self_education=args.self_education,
        enable_51job=args.enable_51job,
        enable_boss=not args.disable_boss,
        enable_zhilian=not args.disable_zhilian,
        enable_liepin=args.enable_liepin,
        enable_waiqi=not args.disable_waiqi,
        headless=args.headless,
    )

    run_pipeline(config)


if __name__ == "__main__":
    main()
