from html import escape
from typing import Any, Dict, List


def _to_number(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def generate_html_report(jobs: List[Dict[str, Any]], output_file: str, top_n: int = 50) -> None:
    top_jobs = sorted(jobs, key=lambda x: _to_number(x.get("value_for_money_score", 0)), reverse=True)[:top_n]

    rows = []
    for idx, job in enumerate(top_jobs, start=1):
        rows.append(
            """
            <tr>
              <td>{rank}</td>
              <td><a href=\"{job_url}\" target=\"_blank\">{job_name}</a></td>
              <td>{company}</td>
              <td>{salary}</td>
              <td>{location}</td>
              <td>{vfm}</td>
              <td>{match}</td>
              <td>{salary_score}</td>
              <td>{company_score}</td>
              <td>{workload_score}</td>
              <td>{reason}</td>
            </tr>
            """.format(
                rank=idx,
                job_url=escape(str(job.get("job_url", ""))),
                job_name=escape(str(job.get("job_name", ""))),
                company=escape(str(job.get("company", ""))),
                salary=escape(str(job.get("salary", ""))),
                location=escape(str(job.get("location", ""))),
                vfm=escape(str(job.get("value_for_money_score", ""))),
                match=escape(str(job.get("company_nature_score", ""))),
                salary_score=escape(str(job.get("commute_score", ""))),
                company_score=escape(str(job.get("experience_score", ""))),
                workload_score=escape(
                    str(
                        _to_number(job.get("skill_stack_score", 0))
                        + _to_number(job.get("business_score", 0))
                        + _to_number(job.get("bonus_score", 0))
                    )
                ),
                reason=escape(str(job.get("gate_reason", "") or job.get("llm_reason", ""))),
            )
        )

    html = """
<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>JobMiner Top {top_n}</title>
  <style>
    :root {{
      --bg: #f4f8f5;
      --card: #ffffff;
      --text: #1e2b22;
      --muted: #5a6a5f;
      --accent: #1f7a4f;
      --accent-soft: #e6f4ec;
      --border: #d7e5da;
    }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      background: radial-gradient(circle at top right, #e6f3eb 0%, var(--bg) 45%, #edf4f0 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1200px;
      margin: 32px auto;
      padding: 0 16px;
    }}
    .head {{
      background: linear-gradient(135deg, #e5f5ea, #fefefe);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 20px;
      margin-bottom: 16px;
    }}
    .head h1 {{
      margin: 0 0 8px;
      font-size: 28px;
    }}
    .head p {{
      margin: 0;
      color: var(--muted);
    }}
    .table-box {{
      background: var(--card);
      border-radius: 16px;
      border: 1px solid var(--border);
      overflow: auto;
      box-shadow: 0 8px 22px rgba(22, 68, 45, 0.08);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1100px;
    }}
    thead th {{
      position: sticky;
      top: 0;
      background: #f0f8f3;
      color: #214c34;
      font-size: 13px;
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }}
    tbody td {{
      font-size: 13px;
      padding: 10px;
      border-bottom: 1px solid #eef3ef;
      vertical-align: top;
    }}
    tbody tr:hover {{
      background: var(--accent-soft);
      transition: background-color 0.2s ease;
    }}
    a {{
      color: var(--accent);
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
    .badge {{
      display: inline-block;
      background: #e9f8ef;
      color: #1f7a4f;
      border: 1px solid #cfe9d7;
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <section class=\"head\">
      <h1>JobMiner 性价比岗位排行</h1>
      <p>展示前 <span class=\"badge\">{top_n}</span> 个岗位，按 value_for_money_score 从高到低排序。</p>
    </section>
    <section class=\"table-box\">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>岗位</th>
            <th>公司</th>
            <th>薪资</th>
            <th>地点</th>
            <th>总分</th>
            <th>公司性质</th>
            <th>通勤距离</th>
            <th>经验匹配</th>
            <th>技能/业务</th>
            <th>门槛原因</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </section>
  </div>
</body>
</html>
""".format(top_n=top_n, rows="\n".join(rows))

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
