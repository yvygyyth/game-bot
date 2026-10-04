# 原子化方法清单（L0 ~ L5）

共 **49** 个原子方法（设计稿 47 个 + `AllTextsQuery` + `VisibleQuery`，见文末说明）。

图例：`✅` 已实现 · `⬜` 接口已定，实现待写

---

## L0 类型层 — `gamebot/types.py`

零第三方依赖，任何层都可以安全导入。

| 对象 | 说明 | 状态 |
|---|---|---|
| `ActionStatus` | `SUCCESS` / `NOT_FOUND` / `TIMEOUT` / `ERROR` | ✅ |
| `ActionResult[T]` | 统一返回信封：`status / value / message / elapsed / meta` | ✅ |
| `Point(x, y)` | 源分辨率整数点 | ✅ |
| `Region(x, y, w, h)` | 源分辨率矩形，半开区间 | ✅ |

`ActionResult` 的四个构造器：

```python
ActionResult.success(value=Point(100, 200), confidence=0.93)
ActionResult.not_found("attack.png 未命中")
ActionResult.timeout("等待 victory.png 超时", waited=60.0)
ActionResult.error("adb 连接断开", exc=exc)
```

辅助方法：`.ok` / `.failed` / `.map(fn)` / `.unwrap(default)` / `.with_elapsed()` /
`.with_meta()` / `.to_dict()`（可 JSON 化）。

---

## L1 截图层 — `gamebot/atomic/session.py`

Session **只负责截图、坐标换算、持有输入后端**，不做任何查询。

| # | 方法 | 签名要点 | 返回 | 状态 |
|---|---|---|---|---|
| 1 | `capture()` | — | `Frame`（全屏/窗口客户区） | ✅ |
| 2 | `capture_region(region)` | `region` 为源分辨率 | `Frame`（origin 保留） | ✅ |
| 3 | `get_screen_size()` | — | `ActionResult[tuple[int,int]]` | ✅ |

附加能力（L5 动作层依赖）：

| 成员 | 说明 | 状态 |
|---|---|---|
| `mapper` / `to_screen()` / `to_logic()` | 逻辑 <-> 源 坐标换算 | ✅ |
| `input` | `InputBackend`，动作层唯一的出口 | ✅ |
| `close()` / 上下文管理器 | 生命周期，幂等 | ✅ |

`CoordinateMapper`：`source_size` 与 `logic_size` 不一致时按比例换算。
`source == logic` 时退化为恒等映射。

---

## L2 Frame 层 — `gamebot/atomic/frame.py`

一次截图的快照 + 全部查询能力。**坐标恒为源分辨率**（Frame 记住自己的 `origin`，
子区域匹配结果自动加回偏移，所以拿到的 Point 永远可以直接点击）。

### 查询类

| # | 方法 | 返回 | 状态 |
|---|---|---|---|
| 4 | `find_image(template, region, confidence, use_pyramid, grayscale)` | `success(value=Point, score=...)` | ⬜ |
| 5 | `find_all_images(template, region, confidence, max_count, min_distance)` | `success(value=list[Point])` | ⬜ |
| 6 | `find_text(text, region, lang, confidence, exact_match)` | `success(value=Point, text=...)` | ⬜ |
| 7 | `find_all_texts(text, region, lang, confidence)` | `success(value=list[Point])` | ⬜ |
| 8 | `read_text(region, lang, confidence)` | `success(value=str)` | ⬜ |
| 9 | `read_number(region, lang, confidence)` | `success(value=int\|float)` | ✅ |
| 10 | `get_pixel(point)` | `success(value=(r, g, b))` | ✅ |
| 11 | `compare_region(region, template, confidence)` | `success(value=similarity)` | ⬜ |
| 12 | `is_image_visible(template, region, confidence)` | `success(value=bool)`（**不是 not_found**） | ⬜ |

### 变换 / 导出

| # | 方法 | 返回 | 状态 |
|---|---|---|---|
| 13 | `crop(region)` | 新 `Frame`（保留坐标系） | ✅ |
| 14 | `to_numpy()` | `np.ndarray` | ✅ |
| 15 | `save(path)` | `success(value=实际路径)` | ✅ |

### 帧内缓存

```python
frame.cached(key, producer)   # 同帧内相同查询只算一次，失败结果也缓存
frame.clear_cache()
```

元信息：`image` / `origin` / `region` / `size` / `frame_id` / `timestamp` / `session`。

---

## L3 Query 层 — `gamebot/atomic/query.py`

把"查什么"变成**可序列化的数据**：能写进 YAML、能复用、能任意组合。

| # | 类型 | 字段 | 状态 |
|---|---|---|---|
| 16 | `ImageQuery` | `template, region, confidence, use_pyramid, grayscale` | ✅ 委托 |
| 17 | `AllImagesQuery` | `template, region, confidence, max_count, min_distance` | ✅ 委托 |
| 18 | `TextQuery` | `text, region, lang, confidence, exact_match` | ✅ 委托 |
| 19 | `AllTextsQuery` | `text, region, lang, confidence` | ✅ 委托 |
| 20 | `NumberQuery` | `region, lang, confidence, comparator` | ✅ 委托 |
| 21 | `PixelQuery` | `point, expected_color, tolerance` | ✅ 委托 |
| 22 | `CompareQuery` | `region, template, confidence, comparator` | ✅ 委托 |
| 23 | `VisibleQuery` | `template, region, confidence` | ✅ 委托 |
| 24 | `AndQuery` | `queries` | ⬜ 依赖 L4 |
| 25 | `OrQuery` | `queries, short_circuit` | ⬜ 依赖 L4 |
| 26 | `NotQuery` | `query, message` | ⬜ 依赖 L4 |

> "委托"指 `run()` 只是把参数转发给 Frame 的对应方法 —— 这部分逻辑已经写好了。
> 真正待实现的是 Frame 里那些被转发到的方法。

`query_registry()` 提供类型名 -> 类的映射，供 YAML 反序列化使用。
`query_from_dict(data)` 待实现。

---

## L4 组合子层 — `gamebot/atomic/combinators.py`

**帧内组合子**（不截图，必须传入帧；失败返回 `not_found`）：

| # | 函数 | 语义 | 状态 |
|---|---|---|---|
| 27 | `find_all_of(frame, queries)` | `Promise.all`：全部命中才成功 | ⬜ |
| 28 | `find_any_of(frame, queries, short_circuit)` | `Promise.race`：任一命中即成功 | ⬜ |
| 29 | `find_first_of(frame, queries)` | 按顺序取第一个成功的（顺序即优先级） | ⬜ |
| 30 | `find_none_of(frame, queries)` | 全部失败才成功；**子查询 error 则整体失败** | ⬜ |
| 31 | `count_hits(frame, queries)` | 统计命中数量 -> `success(value=int)` | ⬜ |

**跨帧组合子**（自己循环截图；失败返回 `timeout`，`meta["last"]` 带最后一次子结果）：

| # | 函数 | 语义 | 状态 |
|---|---|---|---|
| 32 | `wait_any_of(session, queries, timeout, interval, short_circuit)` | 等到任一命中 | ⬜ |
| 33 | `wait_all_of(session, queries, timeout, interval)` | 等到全部命中，**必须在同一帧成立** | ⬜ |
| 34 | `wait_until(session, predicate, timeout, interval)` | 等到谓词成立，返回那帧 | ⬜ |
| 35 | `wait_stable(session, region, threshold, stable_frames, timeout, interval)` | 等到画面稳定 | ⬜ |
| 36 | `wait_disappear(session, query, timeout, interval)` | 等到不再命中 | ⬜ |

> 效率提示：5 个查询用 `find_all_of` 是 **1 次截图 + 5 次匹配**；
> 写成 5 个独立查询就是 5 次截图。能用帧内组合子就别拆开写。

---

## L5 动作层 — `gamebot/atomic/actions.py`

只操作输入，不知道自己在 Windows 还是 Android。
除 `click_image` / `click_text` / `drag_image` 外**都不截图**。

### 点击

| # | 函数 | 返回 | 状态 |
|---|---|---|---|
| 37 | `click_point(session, point, button, clicks, interval)` | `success(value=实际源坐标)` | ⬜ |
| 38 | `click_image(session, template, region, confidence, button, offset)` | 找不到时 `not_found`（**不乱点**） | ⬜ |
| 39 | `click_text(session, text, region, lang, confidence)` | 同上 | ⬜ |
| 40 | `double_click(session, point, interval)` | — | ⬜ |
| 41 | `right_click(session, point)` | — | ⬜ |

### 移动 / 拖拽 / 滚轮

| # | 函数 | 备注 | 状态 |
|---|---|---|---|
| 42 | `move_to(session, point, duration)` | `duration=0` 会漏掉 hover 类 UI | ⬜ |
| 43 | `drag(session, start, end, duration, button)` | Windows 需拆 mouseDown/移动/mouseUp | ⬜ |
| 44 | `drag_image(session, source_template, target, duration, confidence)` | 识图 + 拖拽 | ⬜ |
| 45 | `scroll(session, clicks, point)` | 正数上/前，负数下/后 | ⬜ |

### 键盘

| # | 函数 | 备注 | 状态 |
|---|---|---|---|
| 46 | `type_text(session, text, interval)` | 中文需剪贴板/ADBKeyboard | ⬜ |
| 47 | `press_key(session, key, presses, interval)` | 统一键名，由后端映射 | ⬜ |
| 48 | `hotkey(session, keys)` | pydirectinput 组合键支持有限 | ⬜ |

### 等待

| # | 函数 | 备注 | 状态 |
|---|---|---|---|
| 49 | `sleep(seconds)` | 唯一"什么都不做"的原子方法 | ✅ |

---

## 八、五种典型使用方式

```python
# 模式 1：一次截图，单个查询
frame = session.capture()
result = frame.find_image("attack.png")

# 模式 2：一次截图，多个查询（共享同一张图，时序一致）
frame = session.capture()
hp = frame.read_number(Region(100, 50, 80, 30))
atk = frame.find_image("attack.png")
dfd = frame.find_image("defend.png")

# 模式 3：一次截图，组合查询（AND）
frame = session.capture()
result = find_all_of(frame, [
    ImageQuery("attack.png"),
    ImageQuery("hp_bar.png"),
    TextQuery("Ready"),
])

# 模式 4：一次截图，组合查询（race）
frame = session.capture()
result = find_any_of(frame, [
    ImageQuery("victory.png"),
    ImageQuery("defeat.png"),
    ImageQuery("disconnect.png"),
])

# 模式 5：跨帧等待（内部循环截图）
result = wait_any_of(session, [
    ImageQuery("victory.png"),
    ImageQuery("defeat.png"),
], timeout=60.0)
```

---

## 九、与原设计稿的差异

| 差异 | 原因 |
|---|---|
| 新增 `AllTextsQuery` | L2 有 `find_all_texts`，没有对应的 Query 描述符就没法配置化。 |
| 新增 `VisibleQuery` | "不可见即有效答案"和"找不到即失败"是两种语义（见 architecture.md 决策 2），混用必出 bug。 |
| `QueryLike` 类型别名 | 流程守卫里允许塞 lambda 做临时条件，但主路径仍应是数据化的 Query。 |
| `Session` 增加 `input` / `mapper` | 设计稿要求 L5 只接收 `session` 一个上下文对象，所以输入通道和坐标换算必须挂在 Session 上。 |
| 新增 `AllTextsQuery` 之外的注册表机制 | YAML 里要能写 `type: ImageQuery`，必须有 类型名 -> 类 的映射。 |
