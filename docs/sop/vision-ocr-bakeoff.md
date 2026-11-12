# 视觉 OCR 模型实测（bake-off）

- 日期：2026-11-12 20:23
- 端点：http://127.0.0.1:31415/v1
- 页面：7559b406 p2, 7559b406 p8
- 渲染：zoom=2.0

| 模型 | 页 | 耗时 | 字符数 | 启发式置信 | 判定 |
|------|----|------|--------|------------|------|
| nemotron-parse-2.0 | p2 | 61.7s | ERR | ERR | RateLimitError: Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'ty |

<details><summary>nemotron-parse-2.0 · p2 错误</summary>

```
Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'type': 'routing_error'}}
```

| nemotron-parse-2.0 | p8 | 60.6s | ERR | ERR | RateLimitError: Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'ty |

<details><summary>nemotron-parse-2.0 · p8 错误</summary>

```
Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'type': 'routing_error'}}
```

| glm-4.6v-flash | p2 | 60.3s | ERR | ERR | RateLimitError: Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'ty |

<details><summary>glm-4.6v-flash · p2 错误</summary>

```
Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'type': 'routing_error'}}
```

| glm-4.6v-flash | p8 | 4.8s | 0 | 0.0 | bad |

<details><summary>glm-4.6v-flash · p8 输出预览</summary>

```

```

| llama-3.2-90b-vision | p2 | 75.0s | ERR | ERR | RateLimitError: Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'ty |

<details><summary>llama-3.2-90b-vision · p2 错误</summary>

```
Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'type': 'routing_error'}}
```

| llama-3.2-90b-vision | p8 | 75.1s | ERR | ERR | RateLimitError: Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'ty |

<details><summary>llama-3.2-90b-vision · p8 错误</summary>

```
Error code: 429 - {'error': {'message': 'All models exhausted. Add more API keys or wait for rate limits to reset.', 'type': 'routing_error'}}
```
