import time
from typing import Any, Dict, List, Tuple

from DrissionPage import ChromiumOptions, ChromiumPage


WAIQI_POSITION_URL = "https://waiqi.com/position"


def must_ele(page_or_ele, selector: str, timeout: int = 20, step: float = 0.25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            ele = page_or_ele.ele(selector, timeout=1)
            if ele:
                return ele
        except Exception:
            pass
        time.sleep(step)
    raise TimeoutError(f"Wait element timeout: {selector}")


def safe_text(parent, selector: str, default: str = "") -> str:
    try:
        ele = parent.ele(selector, timeout=1)
        if ele and ele.text:
            return ele.text.strip()
    except Exception:
        pass
    return default


def safe_texts(parent, selector: str) -> List[str]:
    try:
        eles = parent.eles(selector, timeout=1)
        return [e.text.strip() for e in eles if e and e.text and e.text.strip()]
    except Exception:
        return []


def clean_text(text: str) -> str:
    if not text:
        return ""
    return "\n".join(line.rstrip() for line in str(text).replace("\r\n", "\n").split("\n")).strip()


def create_browser(headless: bool = False):
    co = ChromiumOptions()
    co.set_argument("--disable-blink-features=AutomationControlled")
    co.set_user_agent(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    if headless:
        co.headless(True)
    return ChromiumPage(co)


def open_for_login(page) -> None:
    page.get(WAIQI_POSITION_URL)
    print("[神仙外企] 已打开职位页，请在浏览器里完成登录。")
    print("[神仙外企] 登录完成后，回到终端按回车继续。")
    input()
    must_ele(page, "css:.list-wrap", timeout=30)


def find_first_by_text(parent, selector: str, text: str):
    try:
        eles = parent.eles(selector, timeout=2) or []
    except Exception:
        eles = []
    for ele in eles:
        try:
            if (ele.text or "").strip() == text:
                return ele
        except Exception:
            continue
    return None


def select_city(page, city_name: str = "成都") -> None:
    city_trigger = page.ele("css:.select-item .placeholder", timeout=8)
    if not city_trigger:
        city_trigger = find_first_by_text(page, "css:.select-item", "全国")
    if not city_trigger:
        raise RuntimeError("[神仙外企] 未找到城市筛选入口")

    city_trigger.click(by_js=True)
    dialog = must_ele(page, "css:.el-dialog", timeout=15)

    city_item = find_first_by_text(dialog, "css:.city-item", city_name)
    if not city_item:
        raise RuntimeError(f"[神仙外企] 城市弹窗中未找到: {city_name}")
    city_item.click(by_js=True)

    confirm_span = find_first_by_text(dialog, "css:button span", "确认")
    if not confirm_span:
        confirm_span = find_first_by_text(dialog, "css:span", "确认")
    if not confirm_span:
        raise RuntimeError("[神仙外企] 城市弹窗中未找到确认按钮")

    confirm_span.click(by_js=True)
    must_ele(page, "css:.list-wrap .list-cell", timeout=25)
    time.sleep(1.0)


def click_search(page, keyword: str) -> None:
    input_ele = must_ele(page, "css:input.el-input__inner[placeholder*='搜索职位']", timeout=20)
    input_ele.clear()
    input_ele.input(keyword)

    search_span = find_first_by_text(page, "css:span", "搜索")
    if not search_span:
        raise RuntimeError("[神仙外企] 未找到搜索按钮")
    search_span.click(by_js=True)

    must_ele(page, "css:.list-wrap .list-cell", timeout=25)
    time.sleep(1.0)


def get_cards(page):
    return page.eles("css:.list-wrap .list-cell", timeout=4) or []


def parse_card_brief(card) -> Dict[str, Any]:
    title = safe_text(card, "css:.cell-position .list-span-top .val")
    center_tags = safe_texts(card, "css:.cell-position .list-span-center span")

    experience = center_tags[0] if len(center_tags) > 0 else ""
    education = center_tags[1] if len(center_tags) > 1 else ""

    company = safe_text(card, "css:.cell-company .cell-right .list-span-top")
    company_info = safe_texts(card, "css:.cell-company .company-info > div")
    industry = company_info[0] if len(company_info) > 0 else ""
    company_size = company_info[1] if len(company_info) > 1 else ""

    updated_text = safe_text(card, "css:.cell-bottom > div:first-child")
    city = safe_text(card, "css:.cell-bottom .cityOver span")

    return {
        "job_name": title,
        "experience": experience,
        "education": education,
        "company": company,
        "industry": industry,
        "company_size": company_size,
        "updated_text": updated_text,
        "city": city,
    }


def switch_to_new_tab_if_any(page, old_tab_ids: List) -> object:
    try:
        new_tab_ids = [t for t in page.tab_ids if t not in old_tab_ids]
        if not new_tab_ids:
            return page
        tab = page.get_tab(new_tab_ids[-1])
        return tab or page
    except Exception:
        return page


def click_card_and_get_detail_tab(page, index: int) -> Tuple[object, bool]:
    cards = get_cards(page)
    if index >= len(cards):
        raise IndexError("卡片索引越界")

    target = cards[index]
    try:
        target.scroll.to_see()
    except Exception:
        pass

    old_tab_ids = []
    try:
        old_tab_ids = list(page.tab_ids)
    except Exception:
        pass

    target.click(by_js=True)
    time.sleep(1.0)

    detail_tab = switch_to_new_tab_if_any(page, old_tab_ids)
    opened_new_tab = detail_tab is not page
    return detail_tab, opened_new_tab


def parse_detail(detail_page) -> Dict[str, Any]:
    must_ele(detail_page, "css:.detail-item .work-url", timeout=20)

    title = safe_text(detail_page, "css:.position-title")
    company = safe_text(detail_page, "css:.company-name")

    detail_item = detail_page.ele("css:.detail-item", timeout=3)
    detail_tags = safe_texts(detail_item, "css:.content-tag span") if detail_item else []
    jd = safe_text(detail_item, "css:.work-url") if detail_item else ""

    return {
        "detail_title": title,
        "detail_company": company,
        "detail_tags": detail_tags,
        "jd_description": clean_text(jd),
        "detail_url": getattr(detail_page, "url", ""),
    }


def has_next_page(page) -> bool:
    btn = page.ele("css:.el-pagination .btn-next", timeout=2)
    if not btn:
        return False
    cls = (btn.attr("class") or "").lower()
    return "disabled" not in cls and "is-disabled" not in cls


def go_next_page(page) -> bool:
    if not has_next_page(page):
        return False

    btn = page.ele("css:.el-pagination .btn-next", timeout=3)
    if not btn:
        return False

    btn.click(by_js=True)
    must_ele(page, "css:.list-wrap .list-cell", timeout=25)
    time.sleep(1.2)
    return True


def collect_jobs_by_keyword(page, keyword: str, max_jobs: int = 60, max_pages: int = 2) -> List[Dict[str, Any]]:
    click_search(page, keyword)

    results: List[Dict[str, Any]] = []
    seen_keys = set()
    page_idx = 1

    while page_idx <= max_pages and len(results) < max_jobs:
        cards = get_cards(page)
        if not cards:
            break

        for i in range(len(cards)):
            if len(results) >= max_jobs:
                break

            latest_cards = get_cards(page)
            if i >= len(latest_cards):
                break

            brief = parse_card_brief(latest_cards[i])
            dedupe_key = f"{brief['job_name']}|{brief['company']}|{brief['updated_text']}"
            if dedupe_key in seen_keys:
                continue

            detail_page = None
            opened_new_tab = False
            detail: Dict[str, Any] = {}
            try:
                detail_page, opened_new_tab = click_card_and_get_detail_tab(page, i)
                detail = parse_detail(detail_page)
            except Exception:
                detail = {
                    "detail_title": "",
                    "detail_company": "",
                    "detail_tags": [],
                    "jd_description": "",
                    "detail_url": "",
                }
            finally:
                if opened_new_tab and detail_page is not None:
                    try:
                        detail_page.close()
                    except Exception:
                        pass

            item = {
                "source": "waiqi",
                "keyword": keyword,
                "city": brief["city"],
                "job_name": detail.get("detail_title") or brief["job_name"],
                "company": detail.get("detail_company") or brief["company"],
                "experience": brief["experience"],
                "education": brief["education"],
                "industry": brief["industry"],
                "company_size": brief["company_size"],
                "location": brief["city"],
                "salary": "",
                "tags": detail.get("detail_tags", []),
                "jd_labels": detail.get("detail_tags", []),
                "jd_description": detail.get("jd_description", ""),
                "job_url": detail.get("detail_url", ""),
                "updated_text": brief["updated_text"],
            }
            results.append(item)
            seen_keys.add(dedupe_key)

        if len(results) >= max_jobs:
            break

        if not go_next_page(page):
            break
        page_idx += 1

    return results
