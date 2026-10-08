# 招商项目研判基础框架

业务包位于 `src/business/investment/`，由现有 business 插件自动发现。
主 Agent 直接调用 `run_investment_research`，不注册招商子 Agent。
主 Agent 提取项目资料 → 招商 LangGraph → 结构化研判结果 → 主 Agent 加工答复或报告。

## 第一版能力

`workflow.py` 串联核对资料、企业查询、历史案例、产业匹配、准入核算、政策、风险、评分、结果汇总。
仅对外注册图入口工具，底层查询和核算由图内部调用，避免主 Agent 跳过流程。
产业目录、专属政策检索和评分目前明确返回 not_configured，不能假装已经完成。
结果保留查询原文、模拟标识、计算值、规则来源、版本、缺失项与资料风险，供主 Agent 二次加工。
政策可以由主 Agent 使用已有知识库能力补查；图内专属政策数据源留待接入。
图内不做文件写入，也不额外调用 LLM；主 Agent 承担材料提取和综合表达。

节点通过 investment.progress 事件转为 research.progress SSE，前端展示简短进度。
关键资料缺失由主 Agent 使用现有持久化 ask_user 挂起，回答后合并资料重新运行图。
当前图没有内部断点续跑；只读流程重跑，图实例不保存用户或会话状态。

- ProjectBrief：项目数据，金额万元、面积亩，未知指标保持 null。
- AdmissionRules：园区、版本、来源、投资口径和数值阈值。
- investment_review_project：确定性核算三项亩均指标，保留未配置和缺失状态。
- 企业、历史案例查询：默认返回 status=mock 的模拟数据，仅用于演示。
- 政策与产业证据：复用 query_ragwiki，尚无专属政策库过滤和有效期自动校验。
- 补充信息与文件报告：复用 ask_user 和 render_document，沿用现有审批。

数值计算结果不是完整准入结论；目前没有综合评分、产业规则引擎或业务数据库写入。
用户提供的阈值属于待核实输入，工具不会自行验证来源真实性。

## 使用

入口仅 company_name（企业名称）必填；project、rules、focus 为可选。
例如 run_investment_research(company_name="某新能源企业") 即可启动企业研判。
不自动编造项目名称、园区或投资指标；缺失数据在结果中披露，不阻止企业查询。

对主 Agent 说：帮我研判某企业投资 3 亿元建设储能生产基地是否值得重点跟进。
提供目标园区、用地、固定资产投资、达产产值税收和规则资料，或上传材料。
缺失信息通过提问补齐，缺失外部数据会在结论中披露。

## 后续接入

工具集中在 tools/：queries.py 放查询，review.py 放核算，http.py 放 HTTP 公共入口。
不再拆分 provider、service、rules 层；models.py 保留数据校验。
模拟数据不能作为真实信用、风险、经营预测或准入依据。
后续配置 INVESTMENT_COMPANY_URL、INVESTMENT_HISTORY_URL 即启用对应 HTTP 接口。
INVESTMENT_HTTP_METHOD 支持 GET（query 参数）和 POST（JSON），默认 POST。
企业请求字段 company_name，历史请求字段 industry、可选 park_name；实际字段在 queries.py 适配。
INVESTMENT_API_KEY 使用 X-API-Key 头，INVESTMENT_TIMEOUT_SECONDS 默认 30 秒。
仅接入只读接口；失败返回 error，不回退模拟成功，不回传外部异常正文。凭据不要提交。
之后补充产业目录、政策时效过滤、规则版本管理和明确的评分模型。
不把演示数据作为真实企业事实，新增入库操作必须单独审批。
