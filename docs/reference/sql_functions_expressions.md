# DuckDB SQL 函数与表达式 详读摘要（目标版本 1.5.5）

> 本文档基于 DuckDB 官方文档（docs/current，对应 1.5.5）的 `sql/functions/`、`sql/expressions/`、`sql/meta/` 三个目录逐篇研读后整理而成。
> 已忽略 Jekyll frontmatter（`--- ... ---`）与 Liquid 标签（`{% ... %}`），仅保留正文内容。
> 说明：`functions.json` 在本 checkout 中内容为 `[]`（空数组），因此无法从中提取函数分组；函数分类以各 `.md` 文档正文及其生成标记（`categories:`）为准。

---

## 一、总体分类（Function Taxonomy）

DuckDB 的函数可按下述维度划分：

| 大类 | 说明 | 文档来源 |
|---|---|---|
| 聚合函数 Aggregate | 多行进一行（`count`、`sum`、`avg`、近似聚合、统计聚合、有序集合聚合） | `functions/aggregates.md` |
| 标量函数 Scalar | 一行进一行（数值、字符串、日期、条件、哈希、系统、位运算等） | 多个文档 |
| 窗口函数 Window | 在分区内计算（`row_number`、`lag`、`rank` 等） | `functions/window_functions.md` |
| 表函数 Table | 返回结果集（`range()`、`generate_series()`、`duckdb_*` 元数据函数） | `functions/list.md`、`meta/duckdb_table_functions.md` |
| Lambda 函数 | 匿名函数 `lambda x: ...`，用于列表变换/过滤/归约 | `functions/lambda.md` |

**调用约定（重要）**
- 表函数即使无参数也要加括号：`SELECT * FROM duckdb_settings();` 或 `CALL duckdb_settings();`。
- **函数链式调用（dot operator）**：仅适用于标量函数，不适用于表函数。例如 `goose_name.replace('goose','duck')`、`'hello'.upper()`。
- 部分 `duckdb_` 表函数有同名视图（无括号），会过滤掉内部对象；误用无括号形式会命中视图而非表函数。

---

## 二、聚合函数（Aggregate Functions）

### 2.1 通用聚合（General）
| 函数 | 作用 | 示例 |
|---|---|---|
| `count(x)` / `count(*)` | 计数 | `count(*)` |
| `sum(x)` / `avg(x)` | 求和 / 均值 | `sum(amount)` |
| `min(x)` / `max(x)` | 最小 / 最大 | `max(price)` |
| `any_value(x)` | 任意一行的值 | `any_value(name)` |
| `arg_max(x, y)` / `arg_min(x, y)` | 按 y 取最大/最小对应的 x | `arg_max(price, time)` 返回时间最晚的价格 |
| `list(x)` / `string_agg(x [, sep])` | 聚合成列表 / 字符串拼接 | `string_agg(name, ', ')` |
| `product(x)` | 连乘 | `product(qty)` |
| `histogram(x)` | 频次直方图（MAP） | `histogram(category)` → `{a=2, b=1}` |
| `weighted_avg(x, w)` | 加权平均 | `weighted_avg(score, weight)` |

### 2.2 近似聚合（Approximate）
用于大数据集，速度优先、结果近似。
- `approx_count_distinct(x)`（基于 HyperLogLog）
- `approx_quantile(x, q)`（基于 T-Digest）
- `approx_top_k(x, k)`（频率 top-k）
- `reservoir_quantile(x, q, sample_size)`

### 2.3 统计聚合（Statistical）
- 相关性/协方差：`corr(x,y)`、`covar_pop(x,y)`、`covar_samp(x,y)`、`regr_slope(x,y)`、`regr_intercept`、`regr_r2` 等 `regr_*` 系列
- 分布：`stddev_pop`/`stddev_samp`、`var_pop`/`var_samp`、`sem`（标准误差）、`entropy`
- 形状：`skewness`、`kurtosis`/`kurtosis_pop`、`mad`（中位绝对偏差）
- 中心/众数：`median`、`mode`、`quantile_cont(x, q)`/`quantile_disc(x, q)`

### 2.4 有序集合聚合（Ordered-Set Aggregates）
使用 `WITHIN GROUP (ORDER BY ...)` 语法：
- `percentile_cont(q) WITHIN GROUP (ORDER BY x)`
- `percentile_disc(q) WITHIN GROUP (ORDER BY x)`
- `mode() WITHIN GROUP (ORDER BY x)`

### 2.5 杂项
- `grouping(grouping_expr)`：配合 `GROUPING SETS`/`CUBE`/`ROLLUP`，标识聚合层级。

---

## 三、数值与数学函数（Numeric / Math）

### 3.1 运算符
| 运算符 | 说明 |
|---|---|
| `+ - * /` | 四则运算；`/` 为整数除法（整除），`//` 为浮点除法 |
| `%` | 取模 |
| `**` | 幂运算（`pow` 的别名） |
| `!` | 阶乘（后缀） |
| `& | ^ ~` | 按位与/或/异或/取反 |
| `<< >>` | 左移 / 右移 |

### 3.2 常用数学函数（节选）
- 舍入：`round(x [, n])`、`round_even(x)`（银行家舍入）、`ceil`/`floor`/`trunc`
- 最值：`greatest(a, b, ...)`、`least(a, b, ...)`（按字典序，字符串大小写敏感）
- 对数/指数：`ln`、`log`/`log10`/`log2`、`exp`、`pow(x,y)`、`sqrt`、`cbrt`
- 三角/双曲：`sin`/`cos`/`tan` 及反函数、`sinh`/`cosh`/`tanh`、`radians`/`degrees`
- 其他：`abs`、`sign`、`mod`、`gcd`/`lcm`、`factorial`、`gamma`、`isnan`、`isinf`、`nextafter`、`bit_count`、`xor`

> 完整约 78 个数学函数，详见 `functions/numeric.md`。

---

## 四、字符串 / 文本函数（Text / String）

文档标记类别：`[string, regex]` 与 `[text_similarity]`。

### 4.1 运算符与索引
- `string[index]`：1 基字符提取（如 `'DuckDB'[4]` → `k`）。别名 `array_extract`。
- `string[begin:end]`：切片（类 Python，支持负数，`'DuckDB'[:4]` → `Duck`）。
- `||`：字符串/列表/BLOB 拼接（`NULL` 进 `NULL`）。
- `string LIKE target`、`string SIMILAR TO regex`、`string ^@ search`（同 `starts_with`）。

### 4.2 常用文本函数（节选）
| 函数 | 作用 | 示例 |
|---|---|---|
| `length(s)` / `strlen(s)` | 字符数 / 字节数 | `length('Hello🦆')` → 6；`strlen` → 4 |
| `lower`/`upper` | 大小写 | `upper('Hi')` |
| `trim`/`ltrim`/`rtrim(s [, chars])` | 去两端/左/右字符 | `trim('>>test<<','><')` |
| `concat(v...)` / `concat_ws(sep, v...)` | 拼接（跳过 NULL） | `concat_ws(', ', a, b)` |
| `substring(s, start [, len])` | 子串（1 基） | `substring('Hello',2,2)` → `el` |
| `left`/`right(s, n)` | 左/右 n 字符 | `left('Hello',2)` |
| `replace(s, src, tgt)` / `translate(s, from, to)` | 替换 | `replace('hello','l','-')` → `he--o` |
| `contains`/`starts_with`/`suffix`/`prefix`/`instr`/`position` | 包含/前缀/后缀/定位 | `instr('test test','es')` → 2 |
| `split_part(s, sep, idx)` | 按分隔符取第 idx 段 | `split_part('a;b;c',';',2)` → `b` |
| `string_split(s, sep)` / `string_split_regex(s, re)` | 拆成列表 | `string_split('a-b','-')` → `[a,b]` |
| `repeat`/`reverse` | 重复 / 反转 | `reverse('olleh')` |
| `lpad`/`rpad(s, n, ch)` | 补齐至 n 字符 | `lpad('hi',5,'>')` → `>>>hi` |
| `format(fmt, ...)` / `printf(fmt, ...)` | 格式化（fmt / printf 语法） | `format('{} + {} = {}',3,5,8)` |
| `chr`/`unicode`/`ascii` | 码点互转 | `chr(65)` → `A` |
| `hex`/`unhex`/`bin`/`unbin`/`to_base64`/`from_base64`/`to_base(n, radix)` | 编码转换 | `hex('Hi')` |
| `url_encode`/`url_decode` | URL 百分号编解码 | `url_encode('a b')` |
| `nfc_normalize`/`strip_accents` | Unicode 归一化/去重音 | `strip_accents('mühleisen')` |
| `parse_filename`/`parse_dirpath`/`parse_path` | 路径解析（类 Python pathlib） | `parse_filename('/a/b.csv', true)` → `b` |
| `read_text(source)` | 读取文件/通配为 VARCHAR | `read_text('a.txt')` |
| `bar(x, min, max [, w])` | 文本进度条 | `bar(5,0,20,10)` |

### 4.3 哈希函数（字符串）
- `hash(value)`：返回 `UBIGINT`，**非**加密哈希。
- `md5(s)`（VARCHAR）、`md5_number`/`md5_number_lower`/`md5_number_upper`（整数形式）。
- `sha1(value)`、`sha256(value)`：返回 VARCHAR 的加密哈希。

### 4.4 文本相似度（Text Similarity）
| 函数 | 说明 |
|---|---|
| `levenshtein(s1, s2)`（别名 `editdist3`） | 编辑距离 |
| `damerau_levenshtein(s1, s2)` | 含相邻交换的编辑距离 |
| `hamming(s1, s2)`（别名 `mismatches`） | 等长串汉明距离 |
| `jaccard(s1, s2)` | Jaccard 相似度（0–1） |
| `jaro_similarity` / `jaro_winkler_similarity(s1, s2 [, cutoff])` | Jaro / Jaro-Winkler 相似度 |

### 4.5 正则表达式（RE2 引擎）
见 `functions/regular_expressions.md` 与 `pattern_matching.md`：
- `regexp_matches(s, re [, opt])`、`regexp_full_match(s, re)`、`regexp_extract(s, re [, grp])`、`regexp_extract_all`、`regexp_replace(s, re, repl [, opt])`、`regexp_split_to_array`/`regexp_split_to_table`、`regexp_escape`。
- 模式匹配运算符：`LIKE`/`ILIKE`、`SIMILAR TO`、`GLOB`、POSIX `~` / `~*` / `!~`。

---

## 五、日期与时间函数（Date / Time）

### 5.1 类型
DuckDB 支持 `DATE`、`TIME`、`TIMESTAMP`、`TIMESTAMP WITH TIME ZONE`（需 ICU 扩展）、`INTERVAL`（`functions/date.md`、`time.md`、`timestamp.md`、`timestamptz.md`、`interval.md`）。

### 5.2 常用函数
| 函数 | 作用 |
|---|---|
| `current_date` / `current_time` / `now()` / `transaction_timestamp()` | 当前日期/时间 |
| `epoch(s)` / `epoch_ms(ms)` / `to_timestamp(sec)` | 时间戳与 Unix 秒互转 |
| `date_part(part, x)` / `year`/`month`/`day`/`hour`/... | 提取分量 |
| `date_trunc(part, x)` | 截断到指定精度 |
| `date_diff(part, a, b)` | 两时间差（单位 part） |
| `date_add`/`date_sub`/`+ INTERVAL` | 加减间隔 |
| `strftime(x, fmt)` | 格式化（`strftime(t, '%Y-%m-%d')`） |
| `strptime(s, fmt)` / `try_strptime` | 字符串解析为时间戳 |
| `make_date(y,m,d)` / `make_timestamp(...)` / `make_time(h,m,s)` | 构造 |
| `time_bucket(bucket, ts [, offset])` | 时间分桶（1.5 起支持时区参数） |
| `age(a, b)` | 年龄/间隔差 |

> 间隔（`INTERVAL`）支持 `INTERVAL '1' MONTH`、`EXTRACT`、算术运算等。

---

## 六、嵌套类型函数（Nested Types）

### 6.1 列表 / 数组（List / Array）
见 `functions/list.md` 与 `functions/array.md`（类别 `[list]`、`[array]`）。
- 构造与索引：`list_value(4,5,6)`（别名 `list_pack`）、`list[index]`（1 基，别名 `list_extract`/`array_extract`）、切片 `list[begin:end:step]`（类 Python，`list_slice`）。
- 拼接/包含：`list_concat`（别名 `array_concat`，`NULL` 跳过）、`||`、包含判断 `list_contains`（别名 `array_has`）、`list_has_all`（`@>`/`<@`）、`list_has_any`（`&&`）。
- 变换（Lambda）：`list_transform(list, lambda x: ...)`（别名 `apply`/`array_apply`）、`list_filter`、以 `list_reduce(list, lambda x,y: ... [, init])` 归约。
- 排序/去重：`list_sort`（可选 `ASC/DESC`, `NULLS FIRST/LAST`）、`list_reverse_sort`、`list_distinct`、`list_grade_up`、`list_reverse`、`flatten`（降一层）、`list_resize`、`list_unique`（去重计数）。
- 距离/相似度：`list_distance`（`<-` 欧氏）、`list_cosine_distance`（`<=>`）、`list_cosine_similarity`、`list_inner_product`（点积）、`list_negative_inner_product`。
- 聚合式列表函数：`list_aggregate(list, 'min')`（别名 `list_aggr`/`array_aggregate`）及一批便捷重写 `list_sum`/`list_avg`/`list_min`/`list_max`/`list_median`/`list_mode`/`list_histogram`/`list_stddev_samp` 等。
- 列表推导（List Comprehension）：`[upper(x) FOR x IN strings IF len(x) > 0]`。
- 范围：`range(start[, stop][, step])`（stop 不含）、`generate_series(start, stop[, step])`（stop 含）、`generate_subscripts(arr, dim)`；均支持日期区间。
- `unnest(list)`：展开一层（改变基数）。

### 6.2 结构体（Struct）
见 `functions/struct.md`：
- `row(a, b)` / `struct_pack(k:=v, ...)` 构造；`struct_extract(s, 'k')` / `s.k` 取字段；`struct_insert(s, k:=v)` 插入/覆盖；`struct_cat` 合并；`row_to_json`（JSON 文档路径）。
- 表达式层：`struct.*` 可把结构体各键展开为独立列。

### 6.3 映射（Map）
见 `functions/map.md`：
- `map {k: v, ...}`、`map_extract(m, k)` / `m[k]`、`map_contains(m, k)`、`map_keys`/`map_values`、`map_insert`/`map_delete`/`map_update`、`map_from_entries`、`element_at`、`cardinality`。
- 表达式中 `SWITCH(expr, MAP{...}[, default])` 为 CASE 语法糖。

### 6.4 其他嵌套/特殊类型
- `nested.md`：嵌套类型的通用约定（下标、包含、`cardinality`）。
- `union.md`：UNION 类型的 `union_tag`/`union_extract`。
- `enum.md`：ENUM 类型的 `enum_code`/`enum_label`。
- `bitstring.md`：位串（BITSTRING）运算（`& | ~ ^ << >>`、`bitstring_agg`、`bit_count`、`get_bit`）。
- `blob.md`：BLOB（`blob` 字面量 `\x...`、`read_blob`、`length`、`contains`、`concat`、`sha256`/`md5` 可用）。
- `geometry.md`：几何类型（需 spatial 扩展）：`ST_Area`/`ST_Distance`/`ST_AsText` 等（类别由扩展注册）。

---

## 七、Lambda 函数

见 `functions/lambda.md`（**版本相关重点**）。
- 形式：`lambda parameter1, parameter2, ... : expression`（Python 风格）。
- **单箭头写法 `x -> x + 1` 已在 v1.3 弃用**，建议改用 `lambda x : x + 1`。
- 设置项 `lambda_syntax`：`DEFAULT`（允许双冒号，禁止单箭头）、`ENABLE_SINGLE_ARROW`、`DISABLE_SINGLE_ARROW`。
- **弃用路线图**：v1.3 起弃用单箭头；**v1.5 是最后一个默认仍可在不开启开关情况下使用单箭头的版本**；v2.0 默认禁用单箭头；v2.1 移除该开关。
- 应用：`list_transform`、`list_filter`、`list_reduce`、`list_zip_with` 等，以及 `COLUMNS(lambda c: c LIKE '%num%')` 列选择。

---

## 八、条件与工具函数（Utility）

见 `functions/utility.md`：
- 条件：`coalesce(a, b, ...)`（第一非 NULL）、`ifnull(a, b)`、`nullif(a, b)`、`if(cond, a, b)`（等同单条件 CASE）。
- 哈希/编码：`hash`、`md5`/`sha1`/`sha256`（见上）、`checksum`（BLOB）。
- 唯一标识：`uuid()`/`uuidv4()`（随机）、`uuidv7()`（时间有序，1.5 新增系列）；`uuid_extract_timestamp(u)`、`uuid_extract_version(u)`（1.5 新增）。
- 系统/元信息：`version()`、`typeof(x)`、`current_database()`、`current_schema()`、`current_schemas(bool)`、`current_user`、`constant_or_null`、`parser_version()`。
- 其它：`least`/`greatest`（亦属文本/数值章）、`typeof`。

---

## 九、窗口函数（Window Functions）

见 `functions/window_functions.md`：
- 序号类：`row_number()`、`rank()`、`dense_rank()`、`ntile(n)`、`percent_rank()`、`cume_dist()`。
- 取值类：`first_value`/`last_value`/`nth_value(x, n)`、`lag(x [, off][, def])`/`lead(x [, off][, def])`。
- **`fill(x)`（1.5 新增）**：线性插值填补窗口内 NULL。
- 聚合作窗口：`sum(...)`/`avg(...)` 等加 `OVER (PARTITION BY ... ORDER BY ...)`。
- 帧（Framing）：`ROWS` / `RANGE` / `GROUPS`；`BETWEEN ... AND ...`；`UNBOUNDED PRECEDING`/`CURRENT ROW`/`n PRECEDING`；`EXCLUDE`（`CURRENT ROW`/`GROUP`/`TIES`/`NO OTHERS`）。
- 子句：`WINDOW` 命名窗口复用；`QUALIFY` 对窗口函数结果过滤（类 HAVING 之于聚合）。

---

## 十、表达式（Expressions）

### 10.1 运算符优先级与逻辑
- 比较运算符：`< > <= >= = == <> !=`；任一为 NULL 结果为 NULL。`IS DISTINCT FROM` / `IS NOT DISTINCT FROM` 把 NULL 视为相等。
- `BETWEEN x AND y`（等价于 `x<=a AND a<=y`）、`IS [NOT] NULL`（及 `ISNULL`/`NOTNULL` 非标准别名）。
- 逻辑：`AND`/`OR`/`NOT`，三值逻辑。`NULL AND false`→`false`，`NULL OR true`→`true`。
- **组合类型转换（Combination Casting）**：不同类型比较时自动转换（如 `1 = true`、`1 = '1.1'` 在 DuckDB 为真，但与 PostgreSQL 不兼容；无法强制严格类型检查）。

### 10.2 CASE / SWITCH
- `CASE WHEN cond THEN a ELSE b END`；可链式 `WHEN`；`ELSE` 缺省返回 NULL；支持 `CASE expr WHEN v THEN ... END`（switch 形式）。
- `SWITCH(expr, MAP{...}[, default])` 语法糖。

### 10.3 CAST
- `CAST(x AS TYPE)` 或 `x::TYPE`（PostgreSQL 风格）。
- `TRY_CAST(x AS TYPE)`：失败返回 NULL（不抛错）。
- `cast_to_type(x, y)`：转换到另一列的类型（便于宏中保型）。

### 10.4 TRY 表达式
- `TRY(expr)`：子表达式为某行抛错时该行返回 NULL（灵感来自 `TRY_CAST`）。不能用于易变函数、聚合函数、标量子查询（如 `TRY(random())` 报错）。

### 10.5 子查询（Subqueries）
- 标量子查询（返回单值，可用在任意表达式位置）；`ARRAY(subquery)` 收集成列表。
- 量化比较：`ALL` / `ANY` / `SOME`（`x <= ALL (sub)`）。
- `EXISTS` / `NOT EXISTS`（半连接/反连接；DuckDB 自动识别反连接）。
- `IN`：右侧可为元组、列表、MAP（查键）、子查询（单列）、甚至字符串（含子串，等同 `contains`）。
- 相关子查询：子查询引用父查询列，概念上逐行执行。
- 子查询整体作为列名：每行转为一个 STRUCT。

### 10.6 星号与列表达式（Star / COLUMNS）
- `*`、`tbl.*`、`struct.*`（展开结构体键）。
- `SELECT * EXCLUDE (col)` / `REPLACE (...)` / `RENAME (...)`。
- 模式匹配列选择：`SELECT * LIKE 'col%'`、`* GLOB 'col*'`、`* SIMILAR TO 'col.'` 及 `NOT` 变体。
- `COLUMNS(...)`：对多列套用同一表达式；支持正则字符串（如 `COLUMNS('(id|num)')`）、列名列表、`UNPACK`/`*` 解包、`lambda c: c LIKE '%num%'` 过滤、捕获组重命名（`\1`、原名列 `\0`）。

### 10.7 排序规则（Collations）
- 默认 `BINARY`（别名 `C`/`POSIX`），最快但非区域感知。
- 内置：`NOCASE`、`NOACCENT`、`NFC`；可点式组合（如 `NOCASE.NOACCENT`）。
- 全局/`PRAGMA default_collation`、列级 `VARCHAR COLLATE NOACCENT`。
- 区域规则需加载 ICU 扩展（提供 `de`、`zh`、数百种语言/地区 collation）。
- 不同 collation 的列不能直接比较，需手动覆盖。

---

## 十一、元数据 / 系统函数（Meta）

### 11.1 `duckdb_*` 表函数
见 `meta/duckdb_table_functions.md`。命名以 `duckdb_` 前缀、位于 `main` schema，可用 `SELECT * FROM duckdb_x()` 或 `CALL duckdb_x()`。类别完整枚举：
- `duckdb_columns`、`duckdb_constraints`、`duckdb_coordinate_systems`（几何 CRS）、`duckdb_databases`、`duckdb_dependencies`、`duckdb_extensions`、`duckdb_functions`、`duckdb_indexes`、`duckdb_keywords`、`duckdb_log_contexts`、`duckdb_logs`、`duckdb_memory`、`duckdb_optimizers`、`duckdb_prepared_statements`、`duckdb_profiling_settings`、`duckdb_schemas`、`duckdb_secret_types`、`duckdb_secrets`、`duckdb_sequences`、`duckdb_settings`、`duckdb_tables`、`duckdb_temporary_files`、`duckdb_types`、`duckdb_variables`、`duckdb_views`。
- 其中 `duckdb_functions` 的 `function_type` 取值：`table`/`scalar`/`aggregate`/`pragma`/`macro`/`table_macro`，并含 `return_type`、`parameters`、`stability`、`has_side_effects` 等字段——是探查函数分类的权威来源。

### 11.2 Information Schema
见 `meta/information_schema.md`（基于 PostgreSQL 实现，SQL 标准视图）：
- 视图：`character_sets`、`columns`、`constraint_column_usage`、`key_column_usage`、`referential_constraints`、`schemata`、`tables`、`table_constraints`。
- 目录函数：`current_catalog()`、`current_schema()`、`current_schemas(bool)`。
- 多为对 `duckdb_*` 表函数的标准化封装（如 `information_schema.columns` 建立在 `duckdb_columns()` 之上）。

---

## 十二、函数分类总览（用于书籍大纲）

以下为 DuckDB 1.5.5 文档中出现的完整函数/表达式分类（综合各文档标题与 `categories:` 生成标记）：

1. **聚合函数**：通用、近似（HLL/T-Digest/ reservoir）、统计、有序集合、杂项（`grouping`）
2. **标量函数**
   - 数值/数学（算术、幂、阶乘、位运算、三角/双曲、对数/指数、舍入、最值）
   - 字符串/文本（运算、拼接、截取、大小写、填充、拆分、路径、相似度、正则）
   - 日期/时间（DATE/TIME/TIMESTAMP/TIMESTAMPTZ/INTERVAL、截断/差/分桶/格式化）
   - 条件（`CASE`/`IF`/`COALESCE`/`NULLIF`/`IFNULL`）
   - 哈希/编码（`hash`/`md5*`/`sha1`/`sha256`/`hex`/`base64`/`uuid*`）
   - 系统/元信息（`version`/`typeof`/`current_*`/`constants`）
   - 位串（BITSTRING）、BLOB、几何（Geometry，扩展）
3. **嵌套类型函数**：LIST/ARRAY、STRUCT、MAP、UNION、ENUM、Nested 通用
4. **Lambda 函数**（含列表推导）
5. **窗口函数**（序号、取值、填充 `fill`、聚合窗口、帧定义）
6. **表函数**：`range`/`generate_series`、`unnest`、各类 `duckdb_*` 元数据函数、扩展注册表函数
7. **表达式**：运算符优先级、比较/逻辑/BETWEEN/IS NULL、CASE/SWITCH、CAST/TRY_CAST、TRY、子查询、星号与 COLUMNS、排序规则、组合类型转换
8. **元数据/系统视图**：`duckdb_*` 表函数族、`information_schema` 视图族

---

## 十三、版本相关要点（Version-Specific，1.5.5）

- **Lambda 单箭头弃用**：v1.3 弃用 `x -> x+1`；v1.5 为最后一个默认允许单箭头（无需开关）的版本；v2.0 默认禁用；v2.1 移除 `lambda_syntax` 开关。
- **UUID 增强**：`uuidv7()`、`uuid_extract_timestamp(u)`、`uuid_extract_version(u)`（时间有序 UUID 及提取函数）。
- **窗口函数**：`fill()` 线性插值填补 NULL。
- **时间分桶**：`time_bucket` 增加时区参数支持。
- **直方图工具**：`histogram` / `histogram_exact` / `equi_width_bins`（聚合与列表聚合场景）。
- `functions.json` 本 checkout 为空（`[]`），故版本分类以文档正文为准。

---

*整理完毕。本文档聚焦“重要/代表性”函数并给出签名与示例，同时完整枚举分类；如需逐函数细节请回查对应官方文档页面。*
