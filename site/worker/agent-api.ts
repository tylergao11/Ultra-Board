import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath, pathToFileURL } from "node:url";

const SCHEMA_VERSION = 1;
const API_VERSION = "v1";
const SERVICE_NAME = "ultra_board_local_api";
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const POSITIVE_INTEGER_PATTERN = /^[1-9]\d*$/;
const LIMITS = Object.freeze({
  themes: 8,
  boards: 16,
  stockSelectors: 32,
});

const WORKER_DIRECTORY = path.dirname(fileURLToPath(import.meta.url));
const SITE_DIRECTORY = path.dirname(WORKER_DIRECTORY);
const DEFAULT_PUBLIC_ROOT = path.join(SITE_DIRECTORY, "public");
const NEWS_SOURCES_PATH = path.join(
  SITE_DIRECTORY,
  "config",
  "news-sources.json",
);

const SOURCE_CONTRACT = Object.freeze({
  stock_attributes: "kaipanla theme + themes only",
  market_and_limit_facts: "tonghuashun limit_pool only",
  stories: "tonghuashun stories; stock detail required and separately queried",
  judgement_boundary: "facts_only_no_core_score_or_buy_point",
});

class ApiError extends Error {
  constructor(status, code, message, details = undefined) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function response(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
    body,
  };
}

function errorResponse(error) {
  const known = error instanceof ApiError;
  const status = known ? error.status : 500;
  const code = known ? error.code : "INTERNAL_ERROR";
  const message = known ? error.message : "Agent API 内部错误";
  const body = {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    error: {
      code,
      message,
      ...(known && error.details !== undefined
        ? { details: error.details }
        : {}),
    },
  };
  return response(status, body);
}

function stripBom(text) {
  return text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
}

async function readJson(filePath, { missing = "error" } = {}) {
  let text;
  try {
    text = await readFile(filePath, "utf8");
  } catch (error) {
    if (error && error.code === "ENOENT" && missing === "null") {
      return null;
    }
    if (error && error.code === "ENOENT") {
      throw new ApiError(503, "DATA_CONTRACT_ERROR", "正式数据组件缺失", {
        path: filePath,
      });
    }
    throw error;
  }
  try {
    return JSON.parse(stripBom(text));
  } catch {
    throw new ApiError(503, "DATA_CONTRACT_ERROR", "JSON 数据组件无法解析", {
      path: filePath,
    });
  }
}

function publicRoot(options = {}) {
  return path.resolve(
    options.publicRoot ||
      process.env.ULTRA_BOARD_PUBLIC_ROOT ||
      DEFAULT_PUBLIC_ROOT,
  );
}

function dataRoot(options = {}) {
  return path.join(publicRoot(options), "agent-data", "v1");
}

function isValidDate(value) {
  if (!DATE_PATTERN.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function requireManifestContract(manifest) {
  const dates = manifest?.available_dates;
  if (
    !manifest ||
    manifest.schema_version !== SCHEMA_VERSION ||
    manifest.api_version !== API_VERSION ||
    manifest.status !== "ready" ||
    manifest.publication_ready !== true ||
    typeof manifest.data_revision !== "string" ||
    !manifest.data_revision.startsWith("sha256:") ||
    !Array.isArray(dates) ||
    dates.some((date) => !isValidDate(date)) ||
    new Set(dates).size !== dates.length ||
    dates.some((date, index) => index > 0 && dates[index - 1] >= date) ||
    !manifest.range ||
    manifest.range.start !== dates[0] ||
    manifest.range.end !== dates.at(-1)
  ) {
    throw new ApiError(
      503,
      "DATA_CONTRACT_ERROR",
      "正式 manifest 不符合发布合同",
    );
  }
  return manifest;
}

async function loadManifest(options = {}, { required = true } = {}) {
  const manifestPath = path.join(dataRoot(options), "manifest.json");
  const manifest = await readJson(manifestPath, { missing: "null" });
  if (manifest === null) {
    if (!required) {
      return null;
    }
    throw new ApiError(
      503,
      "DATA_NOT_READY",
      "正式数据尚未导出；先检查 /api/v1/health",
    );
  }
  return requireManifestContract(manifest);
}

function requireDayContract(document, date) {
  if (
    !document ||
    document.schema_version !== SCHEMA_VERSION ||
    document.api_version !== API_VERSION ||
    document.component_type !== "day" ||
    document.date !== date ||
    !document.day
  ) {
    throw new ApiError(
      503,
      "DATA_CONTRACT_ERROR",
      `${date} 正式单日发布外壳不符合 Schema`,
    );
  }
  const component = document.day;
  if (
    component.date !== date ||
    !component.coverage ||
    component.coverage.fact_ready !== true ||
    component.coverage.stock_story_complete !== true ||
    !Array.isArray(component.stocks) ||
    !component.stories ||
    !Array.isArray(component.stories.records) ||
    !Array.isArray(component.source_theme_index) ||
    !Array.isArray(component.source_sector_index)
  ) {
    throw new ApiError(
      503,
      "DATA_CONTRACT_ERROR",
      `${date} 正式单日组件不符合 Schema`,
    );
  }
  for (const stock of component.stocks) {
    if (
      !stock ||
      stock.date !== date ||
      typeof stock.code !== "string" ||
      !stock.code ||
      typeof stock.name !== "string" ||
      !stock.name ||
      !stock.attributes ||
      !stock.limit_facts
    ) {
      throw new ApiError(
        503,
        "DATA_CONTRACT_ERROR",
        `${date} 个股组件不符合 Schema`,
      );
    }
  }
  return component;
}

async function loadDay(date, manifest, options = {}) {
  if (!manifest.available_dates.includes(date)) {
    throw new ApiError(404, "DATE_NOT_FOUND", "日期未正式发布", {
      date,
    });
  }
  const componentPath = path.join(dataRoot(options), "days", `${date}.json`);
  const component = await readJson(componentPath);
  return requireDayContract(component, date);
}

function assertKnownParameters(searchParams, allowed) {
  const unknown = [...new Set(searchParams.keys())].filter(
    (name) => !allowed.has(name),
  );
  if (unknown.length) {
    throw new ApiError(
      400,
      "UNKNOWN_QUERY_PARAMETER",
      "出现合同外查询参数",
      { parameters: unknown },
    );
  }
}

function singleParameter(searchParams, name, { required = false } = {}) {
  const values = searchParams.getAll(name);
  if (values.length > 1) {
    throw new ApiError(
      400,
      "DUPLICATE_QUERY_PARAMETER",
      `${name} 只能出现一次`,
      { parameter: name },
    );
  }
  const value = values.length ? values[0].trim() : null;
  if (required && !value) {
    throw new ApiError(400, "INVALID_DATE", `${name} 为必填参数`, {
      parameter: name,
    });
  }
  return value;
}

function dateParameter(searchParams) {
  const date = singleParameter(searchParams, "date", { required: true });
  if (!isValidDate(date)) {
    throw new ApiError(400, "INVALID_DATE", "date 必须是有效的 YYYY-MM-DD", {
      date,
    });
  }
  return date;
}

function repeatedText(searchParams, name, limit) {
  const rawValues = searchParams.getAll(name);
  if (rawValues.length > limit) {
    throw new ApiError(400, "QUERY_LIMIT_EXCEEDED", `${name} 参数超过上限`, {
      parameter: name,
      limit,
      received: rawValues.length,
    });
  }
  const values = rawValues.map((value) => value.trim());
  if (values.some((value) => !value)) {
    throw new ApiError(400, "INVALID_QUERY_PARAMETER", `${name} 不能为空`, {
      parameter: name,
    });
  }
  return [...new Set(values)];
}

function positiveInteger(value, name) {
  if (value === null) {
    return null;
  }
  if (!POSITIVE_INTEGER_PATTERN.test(value)) {
    throw new ApiError(
      400,
      "INVALID_BOARD_RANGE",
      `${name} 必须是大于等于 1 的整数`,
      { parameter: name, value },
    );
  }
  return Number(value);
}

function parseDayQuery(searchParams) {
  assertKnownParameters(
    searchParams,
    new Set(["date", "theme", "theme_match", "board", "min_board", "max_board"]),
  );
  const date = dateParameter(searchParams);
  const themes = repeatedText(searchParams, "theme", LIMITS.themes);
  const themeMatchRaw = singleParameter(searchParams, "theme_match");
  if (themeMatchRaw !== null && themes.length === 0) {
    throw new ApiError(
      400,
      "INVALID_THEME_MATCH",
      "未传 theme 时不能使用 theme_match",
    );
  }
  const themeMatch = themeMatchRaw || "any";
  if (!new Set(["any", "all"]).has(themeMatch)) {
    throw new ApiError(
      400,
      "INVALID_THEME_MATCH",
      "theme_match 只能是 any 或 all",
    );
  }

  const boardTexts = repeatedText(searchParams, "board", LIMITS.boards);
  const boards = boardTexts.map((value) => {
    if (!POSITIVE_INTEGER_PATTERN.test(value)) {
      throw new ApiError(
        400,
        "INVALID_BOARD_RANGE",
        "board 必须是大于等于 1 的整数",
        { value },
      );
    }
    return Number(value);
  });
  const minBoard = positiveInteger(
    singleParameter(searchParams, "min_board"),
    "min_board",
  );
  const maxBoard = positiveInteger(
    singleParameter(searchParams, "max_board"),
    "max_board",
  );
  if (boards.length && (minBoard !== null || maxBoard !== null)) {
    throw new ApiError(
      400,
      "BOARD_FILTER_CONFLICT",
      "board 不能与 min_board 或 max_board 同时使用",
    );
  }
  if (minBoard !== null && maxBoard !== null && minBoard > maxBoard) {
    throw new ApiError(
      400,
      "INVALID_BOARD_RANGE",
      "min_board 不能大于 max_board",
    );
  }
  return {
    date,
    themes,
    themeMatch,
    boards: [...new Set(boards)],
    minBoard,
    maxBoard,
  };
}

function stockThemes(stock) {
  const attributes = stock.attributes || {};
  return [
    ...new Set(
      [
        attributes.source_main_theme,
        ...(attributes.source_candidate_themes || []),
      ].filter(Boolean),
    ),
  ];
}

function stockMatches(stock, query) {
  const themes = stockThemes(stock);
  if (query.themes.length) {
    const matches = query.themes.map((theme) => themes.includes(theme));
    if (query.themeMatch === "all" ? matches.includes(false) : !matches.includes(true)) {
      return false;
    }
  }
  const boards = stock.limit_facts?.boards;
  if (query.boards.length && !query.boards.includes(boards)) {
    return false;
  }
  if (query.minBoard !== null && (!Number.isInteger(boards) || boards < query.minBoard)) {
    return false;
  }
  if (query.maxBoard !== null && (!Number.isInteger(boards) || boards > query.maxBoard)) {
    return false;
  }
  return true;
}

function stockSummary(stock) {
  const facts = stock.limit_facts || {};
  const attributes = stock.attributes || {};
  return {
    code: stock.code,
    name: stock.name,
    boards: facts.boards ?? null,
    board_type: facts.board_type ?? null,
    main_theme: attributes.source_main_theme ?? null,
    themes: stockThemes(stock),
    first_limit_time: facts.first_limit_time ?? null,
  };
}

function publicStories(stories) {
  const records = Array.isArray(stories?.records) ? stories.records : [];
  const result = { ...stories };
  delete result.stock_records;
  result.records = records.map((record) => {
    const clean = { ...record };
    delete clean.stocks;
    return clean;
  });
  result.contract = "默认展示题材故事；个股故事必须通过 /stocks 按需获取。";
  return result;
}

function marketSummary(market) {
  const keys = [
    "kaipanla_stock_count",
    "ths_limit_up_count",
    "first_board_count",
    "higher_board_count",
    "max_boards",
    "max_board_holders",
    "board_counts",
    "market_mood",
    "rise_count",
    "fall_count",
    "source_limit_up_count",
    "source_natural_limit_up_count",
    "limit_down_count",
    "natural_limit_down_count",
  ];
  return Object.fromEntries(
    keys.filter((key) => Object.hasOwn(market || {}, key)).map((key) => [key, market[key]]),
  );
}

function dayBody(component, manifest, query) {
  const filteredStocks = component.stocks.filter((stock) => stockMatches(stock, query));
  const filtersActive = Boolean(
    query.themes.length ||
      query.boards.length ||
      query.minBoard !== null ||
      query.maxBoard !== null,
  );
  const dateIndex = manifest.available_dates.indexOf(query.date);
  const requestedThemes = new Set(query.themes);
  return {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    view: "single_day_facts",
    data_revision: manifest.data_revision,
    information_cutoff: query.date,
    trade_date: query.date,
    scope: {
      mode: filtersActive ? "filtered" : "market",
      themes: query.themes,
      theme_match: query.themes.length ? query.themeMatch : null,
      boards: query.boards,
      min_board: query.minBoard,
      max_board: query.maxBoard,
      filter_join: "theme_and_board",
      contract: "同维度多值按查询模式组合，不同维度取交集。",
    },
    source_contract: SOURCE_CONTRACT,
    coverage: component.coverage,
    day: {
      date: query.date,
      market: marketSummary(component.market),
      source_sector_index: component.source_sector_index,
      source_theme_index: query.themes.length
        ? component.source_theme_index.filter((record) =>
            requestedThemes.has(record.theme),
          )
        : component.source_theme_index,
      theme_stories: publicStories(component.stories),
      expanded_stock_count: filteredStocks.length,
      stocks: filteredStocks.map(stockSummary),
      source_issues: component.source_issues || [],
    },
    navigation: {
      previous_available_date:
        dateIndex > 0 ? manifest.available_dates[dateIndex - 1] : null,
      next_available_date:
        dateIndex >= 0 && dateIndex < manifest.available_dates.length - 1
          ? manifest.available_dates[dateIndex + 1]
          : null,
    },
  };
}

function storyRowsForStock(component, stock) {
  const stories = component.stories || {};
  const result = [];
  for (const record of stories.stock_records || []) {
    if (record.code !== stock.code && record.name !== stock.name) {
      continue;
    }
    result.push({
      source_position: record.stock_position ?? null,
      headline: null,
      context: null,
      sector_story: null,
      stock_story: {
        code: record.code || stock.code,
        name: record.name || stock.name,
        story: record.story,
        story_source: record.story_source || stories.source,
      },
    });
  }
  for (const group of stories.records || []) {
    for (const record of group.stocks || []) {
      if (record.code !== stock.code && record.name !== stock.name) {
        continue;
      }
      result.push({
        source_position: group.source_position ?? null,
        headline: group.headline ?? null,
        context: group.context ?? null,
        sector_story: group.story ?? null,
        stock_story: {
          code: record.code || stock.code,
          name: record.name || stock.name,
          story: record.story,
          story_source: record.story_source || stories.source,
        },
      });
    }
  }
  return result;
}

function parseStockQuery(searchParams) {
  assertKnownParameters(searchParams, new Set(["date", "code", "name"]));
  const date = dateParameter(searchParams);
  const selectors = [
    ...searchParams.getAll("code").map((value) => ({
      by: "code",
      value: value.trim(),
    })),
    ...searchParams.getAll("name").map((value) => ({
      by: "name",
      value: value.trim(),
    })),
  ];
  if (!selectors.length) {
    throw new ApiError(
      400,
      "STOCK_SELECTOR_REQUIRED",
      "/stocks 至少需要一个 code 或 name",
    );
  }
  if (selectors.some((selector) => !selector.value)) {
    throw new ApiError(
      400,
      "INVALID_QUERY_PARAMETER",
      "code/name 选择器不能为空",
    );
  }
  const uniqueSelectors = [
    ...new Map(
      selectors.map((selector) => [`${selector.by}\u0000${selector.value}`, selector]),
    ).values(),
  ];
  if (uniqueSelectors.length > LIMITS.stockSelectors) {
    throw new ApiError(
      400,
      "QUERY_LIMIT_EXCEEDED",
      "唯一股票选择器超过上限",
      { limit: LIMITS.stockSelectors, received: uniqueSelectors.length },
    );
  }
  return { date, selectors: uniqueSelectors };
}

function selectStocks(component, query) {
  const byCode = new Map(component.stocks.map((stock) => [stock.code, stock]));
  const byName = new Map();
  for (const stock of component.stocks) {
    const values = byName.get(stock.name) || [];
    values.push(stock);
    byName.set(stock.name, values);
  }
  const selected = new Map();
  const missing = [];
  for (const selector of query.selectors) {
    let stock = null;
    if (selector.by === "code") {
      stock = byCode.get(selector.value) || null;
    } else {
      const matches = byName.get(selector.value) || [];
      if (matches.length > 1) {
        throw new ApiError(
          409,
          "AMBIGUOUS_STOCK_NAME",
          "股票名称无法唯一定位，请改用代码",
          { name: selector.value, codes: matches.map((item) => item.code) },
        );
      }
      stock = matches[0] || null;
    }
    if (!stock) {
      missing.push(selector);
      continue;
    }
    const current = selected.get(stock.code) || {
      stock,
      matched_selectors: [],
    };
    current.matched_selectors.push(selector);
    selected.set(stock.code, current);
  }
  if (missing.length) {
    throw new ApiError(
      404,
      "STOCK_NOT_FOUND",
      "至少一个股票选择器未命中",
      { selectors: missing },
    );
  }
  return [...selected.values()];
}

function stockBody(component, manifest, query) {
  const selected = selectStocks(component, query);
  const rows = selected.map(({ stock, matched_selectors: matchedSelectors }) => ({
    matched_selectors: matchedSelectors,
    stock,
    stories: storyRowsForStock(component, stock),
  }));
  const incomplete = rows
    .filter(
      (row) =>
        !row.stories.length ||
        row.stories.some(
          (story) => !String(story.stock_story?.story || "").trim(),
        ),
    )
    .map((row) => row.stock.code);
  if (incomplete.length) {
    throw new ApiError(
      503,
      "STOCK_STORY_INCOMPLETE",
      "至少一只股票的故事缺失或正文为空",
      { codes: incomplete },
    );
  }
  return {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    view: "stock_details",
    data_revision: manifest.data_revision,
    information_cutoff: query.date,
    trade_date: query.date,
    count: rows.length,
    stocks: rows,
  };
}

function calendarBody(manifest) {
  return {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    view: "trading_calendar",
    data_revision: manifest.data_revision,
    publication_ready: manifest.publication_ready,
    generated_at: manifest.generated_at,
    range: manifest.range,
    count: manifest.available_dates.length,
    available_dates: manifest.available_dates,
  };
}

function healthBody(manifest) {
  return {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    service: SERVICE_NAME,
    status: "ok",
    data: manifest
      ? {
          status: "ready",
          publication_ready: true,
          revision: manifest.data_revision,
          generated_at: manifest.generated_at,
          range: manifest.range,
          available_date_count: manifest.available_dates.length,
        }
      : {
          status: "pending_export",
          publication_ready: false,
          revision: null,
          generated_at: null,
          range: null,
          available_date_count: 0,
        },
  };
}

function rootBody(url) {
  const base = `${url.origin}/api/v1`;
  return {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    service: SERVICE_NAME,
    judgement_boundary: SOURCE_CONTRACT.judgement_boundary,
    call_order: ["health", "calendar", "day", "stocks"],
    endpoints: {
      health: `${base}/health`,
      calendar: `${base}/calendar`,
      day: `${base}/day?date={YYYY-MM-DD}`,
      stocks: `${base}/stocks?date={YYYY-MM-DD}&code={CODE}`,
      themes: `${base}/themes?date={YYYY-MM-DD}`,
      stories: `${base}/stories?date={YYYY-MM-DD}`,
      meta: `${base}/meta`,
      guide: `${base}/guide`,
      openapi: `${base}/openapi`,
      news_sources: `${base}/news/sources`,
    },
  };
}

function metaBody() {
  return {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    view: "api_meta",
    query_limits: {
      themes_per_day_request: LIMITS.themes,
      boards_per_day_request: LIMITS.boards,
      unique_stock_selectors_per_request: LIMITS.stockSelectors,
    },
    day_scope: "one_formally_published_trading_day_per_request",
    theme_source: "kaipanla theme/themes exact match",
    board_source: "tonghuashun limit_pool boards",
    null_policy: "source missing or unconfirmed; never rewrite as zero or false",
    atomic_stock_details: true,
    source_contract: SOURCE_CONTRACT,
  };
}

function guideBody() {
  return {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    view: "agent_guide",
    steps: [
      {
        order: 1,
        endpoint: "/api/v1/health",
        rule: "只有 data.status=ready 且 publication_ready=true 时继续。",
      },
      {
        order: 2,
        endpoint: "/api/v1/calendar",
        rule: "只从 available_dates 选择正式交易日。",
      },
      {
        order: 3,
        endpoint: "/api/v1/day?date=T",
        rule: "一次只读一个交易日；跨日按 navigation 指针再次请求。",
      },
      {
        order: 4,
        endpoint: "/api/v1/stocks?date=T&code=...",
        rule: "价格、换手、封单、终封、开板与逐股故事按需批量读取。",
      },
    ],
    boundaries: [
      "context 与同花顺故事不覆盖开盘啦个股属性。",
      "null 表示来源未提供或无法确认。",
      "任一股票故事不完整时，整批详情请求失败。",
      "事实接口不生成核心、评分、接力或买点判断。",
    ],
  };
}

function openApiBody(url) {
  const dateParameterSchema = {
    name: "date",
    in: "query",
    required: true,
    schema: { type: "string", format: "date" },
  };
  return {
    openapi: "3.1.0",
    info: {
      title: "Ultra-Board Single Trading Day Facts API",
      version: API_VERSION,
      description: "只读正式发布组件；一次请求只返回一个交易日。",
    },
    servers: [{ url: url.origin }],
    paths: {
      "/api/v1": { get: { summary: "机器发现入口", responses: { 200: { description: "OK" } } } },
      "/api/v1/health": { get: { summary: "数据发布状态", responses: { 200: { description: "OK" } } } },
      "/api/v1/calendar": { get: { summary: "正式交易日", responses: { 200: { description: "OK" } } } },
      "/api/v1/day": {
        get: {
          summary: "单交易日概览",
          parameters: [
            dateParameterSchema,
            { name: "theme", in: "query", schema: { type: "array", maxItems: LIMITS.themes, items: { type: "string" } } },
            { name: "theme_match", in: "query", schema: { type: "string", enum: ["any", "all"] } },
            { name: "board", in: "query", schema: { type: "array", maxItems: LIMITS.boards, items: { type: "integer", minimum: 1 } } },
            { name: "min_board", in: "query", schema: { type: "integer", minimum: 1 } },
            { name: "max_board", in: "query", schema: { type: "integer", minimum: 1 } },
          ],
          responses: { 200: { description: "OK" }, 400: { description: "Invalid query" }, 404: { description: "Date not found" } },
        },
      },
      "/api/v1/stocks": {
        get: {
          summary: "批量个股详情",
          parameters: [
            dateParameterSchema,
            { name: "code", in: "query", schema: { type: "array", items: { type: "string" } } },
            { name: "name", in: "query", schema: { type: "array", items: { type: "string" } } },
          ],
          responses: { 200: { description: "OK" }, 404: { description: "Stock not found" }, 503: { description: "Story or data incomplete" } },
        },
      },
      "/api/v1/themes": { get: { summary: "单日题材索引", parameters: [dateParameterSchema], responses: { 200: { description: "OK" } } } },
      "/api/v1/stories": { get: { summary: "单日板块故事", parameters: [dateParameterSchema], responses: { 200: { description: "OK" } } } },
      "/api/v1/meta": { get: { summary: "参数与边界", responses: { 200: { description: "OK" } } } },
      "/api/v1/guide": { get: { summary: "Agent 调用指南", responses: { 200: { description: "OK" } } } },
      "/api/v1/openapi": { get: { summary: "OpenAPI 3.1 合同", responses: { 200: { description: "OK" } } } },
      "/api/v1/news/sources": { get: { summary: "新闻与公告来源白名单", responses: { 200: { description: "OK" } } } },
    },
  };
}

async function dateOnlyComponent(url, options) {
  assertKnownParameters(url.searchParams, new Set(["date"]));
  const date = dateParameter(url.searchParams);
  const manifest = await loadManifest(options);
  const component = await loadDay(date, manifest, options);
  return { date, manifest, component };
}

async function route(url, options = {}) {
  const pathname = url.pathname.length > 1
    ? url.pathname.replace(/\/$/, "")
    : url.pathname;
  if (pathname === "/api/v1") {
    assertKnownParameters(url.searchParams, new Set());
    return response(200, rootBody(url));
  }
  if (pathname === "/api/v1/health") {
    assertKnownParameters(url.searchParams, new Set());
    const manifest = await loadManifest(options, { required: false });
    return response(200, healthBody(manifest));
  }
  if (pathname === "/api/v1/calendar") {
    assertKnownParameters(url.searchParams, new Set());
    return response(200, calendarBody(await loadManifest(options)));
  }
  if (pathname === "/api/v1/day") {
    const query = parseDayQuery(url.searchParams);
    const manifest = await loadManifest(options);
    const component = await loadDay(query.date, manifest, options);
    return response(200, dayBody(component, manifest, query));
  }
  if (pathname === "/api/v1/stocks") {
    const query = parseStockQuery(url.searchParams);
    const manifest = await loadManifest(options);
    const component = await loadDay(query.date, manifest, options);
    return response(200, stockBody(component, manifest, query));
  }
  if (pathname === "/api/v1/themes") {
    const { date, manifest, component } = await dateOnlyComponent(url, options);
    return response(200, {
      schema_version: SCHEMA_VERSION,
      api_version: API_VERSION,
      view: "theme_index",
      data_revision: manifest.data_revision,
      information_cutoff: date,
      trade_date: date,
      count: component.source_theme_index.length,
      themes: component.source_theme_index,
    });
  }
  if (pathname === "/api/v1/stories") {
    const { date, manifest, component } = await dateOnlyComponent(url, options);
    return response(200, {
      schema_version: SCHEMA_VERSION,
      api_version: API_VERSION,
      view: "theme_stories",
      data_revision: manifest.data_revision,
      information_cutoff: date,
      trade_date: date,
      stories: publicStories(component.stories),
    });
  }
  if (pathname === "/api/v1/meta") {
    assertKnownParameters(url.searchParams, new Set());
    return response(200, metaBody());
  }
  if (pathname === "/api/v1/guide") {
    assertKnownParameters(url.searchParams, new Set());
    return response(200, guideBody());
  }
  if (pathname === "/api/v1/openapi") {
    assertKnownParameters(url.searchParams, new Set());
    return response(200, openApiBody(url));
  }
  if (pathname === "/api/v1/news/sources") {
    assertKnownParameters(url.searchParams, new Set());
    const configured = await readJson(NEWS_SOURCES_PATH);
    if (
      configured?.schema_version !== SCHEMA_VERSION ||
      !Array.isArray(configured.sources)
    ) {
      throw new ApiError(
        503,
        "DATA_CONTRACT_ERROR",
        "新闻来源白名单配置无效",
      );
    }
    return response(200, {
      schema_version: SCHEMA_VERSION,
      api_version: API_VERSION,
      view: "news_source_allowlist",
      count: configured.sources.length,
      sources: configured.sources,
      contract: "仅允许访问列出的官方或已约定来源；不得用新闻补造个股故事。",
    });
  }
  throw new ApiError(404, "ENDPOINT_NOT_FOUND", "API 端点不存在", {
    path: pathname,
  });
}

export async function requestAgentApi(pathAndQuery, options = {}) {
  let url;
  try {
    url = new URL(pathAndQuery, options.origin || "http://127.0.0.1");
  } catch {
    return errorResponse(
      new ApiError(400, "INVALID_URL", "请求地址无法解析"),
    );
  }
  if (url.origin !== (options.origin || "http://127.0.0.1")) {
    return errorResponse(
      new ApiError(400, "INVALID_URL", "本地 API 只接受相对路径"),
    );
  }
  try {
    return await route(url, options);
  } catch (error) {
    return errorResponse(error);
  }
}

async function main() {
  const pathAndQuery = process.argv[2];
  if (!pathAndQuery) {
    process.stderr.write("用法: npm run api -- \"/api/v1/health\"\n");
    process.exitCode = 2;
    return;
  }
  const apiResponse = await requestAgentApi(pathAndQuery);
  const envelope = {
    schema_version: SCHEMA_VERSION,
    api_version: API_VERSION,
    tool: SERVICE_NAME,
    request: {
      method: "GET",
      path: pathAndQuery,
      public_root: publicRoot(),
    },
    response: apiResponse,
  };
  process.stdout.write(`${JSON.stringify(envelope, null, 2)}\n`);
}

const entryPoint = process.argv[1]
  ? pathToFileURL(path.resolve(process.argv[1])).href
  : null;
if (entryPoint === import.meta.url) {
  await main();
}
