# JobMiner Code Package

这个目录是 JobMiner 的核心代码，可单独作为一个 Python 包仓库发布。

## 功能概览

- 多站点采集：Boss、智联、神仙外企（默认启用）
- 可选站点：猎聘、51job（默认关闭）
- 基于规则的硬门槛过滤：学历、城市、风险词
- 四维评分：公司平台、通勤距离、经验要求、核心匹配度
- 关键词级容错：单个关键词失败会跳过继续
- 增量存档：每个关键词完成后写入原始结果文件

## 运行方式

在包含配置文件的目录执行：

python -m jobminer.main --config config.json

说明：
- config.json 可以放在仓库根目录，也可以放在任意路径，只要传入 --config 即可。
- 建议首次运行使用非 headless，方便完成站点登录。

## 四维评分关键词配置

现在支持通过配置文件中的 score_keywords 自定义四个维度的评分关键词：

- company_platform：公司平台
- commute_distance：通勤距离
- experience_requirement：经验要求
- core_match：核心匹配度

示例：

{
  "score_keywords": {
    "company_platform": ["外企", "国企", "央企", "上市", "头部", "龙头"],
    "commute_distance": ["锦江", "青羊", "金牛", "武侯", "成华", "高新区", "天府新区"],
    "experience_requirement": ["1-3年", "3-5年", "经验不限", "可放宽"],
    "core_match": ["SQL", "Python", "数据分析", "数据治理", "运营分析", "看板"]
  }
}

评分规则说明：
- 如果某个维度配置了关键词：按命中比例换算该维度分值上限。
- 如果某个维度未配置关键词：回退到系统默认规则。

## 代码结构

- main.py：命令行入口
- pipeline.py：采集编排、去重、过滤、评分主流程
- extract_boss.py：Boss 抓取
- extract_zhilian.py：智联抓取
- extract_shenxianwaiqi.py：神仙外企抓取
- extract_liepin.py：猎聘抓取
- extract_51job.py：51job 抓取
- llm_client.py：关键词生成调用
- report.py：HTML 报告
- resume_loader.py：简历读取

## 发布建议

如果你只发布这个目录，建议仓库根目录再补充：
- requirements.txt
- config.example.json（不含真实密钥）
- .gitignore
