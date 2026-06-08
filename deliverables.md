![Overview](overview.png)

# PS2 Deliverables: Production Readiness Audit of `mini_agent`

## Assignment Chosen

I am choosing **PS2 - Public Repo Audit**.

Selected repository:

```text
https://github.com/sergenes/mini_agent
```

The goal is to treat this prototype AI agent as if it were going live and evaluate what would break, what is fragile, what is missing, and what I would fix first.

## 1. Production Readiness Audit

### Understanding the Repository

`mini_agent` is a minimal AI agent built without a full agent framework. It uses Python, provider abstractions, tools, and a deterministic loop:

```text
Receive user task
  |
  v
Call LLM
  |
  v
If tool calls are requested, execute tools
  |
  v
Append tool results to conversation
  |
  v
Continue until final answer
```

The repo supports three operating modes:

- **Local mode:** all model calls go to a local Ollama model.
- **Remote mode:** model calls go to a cloud provider such as OpenAI, Anthropic, or Gemini.
- **Mixed mode:** a local model orchestrates the task and delegates complex subtasks to a remote model through `ask_remote()`.

The repo already includes important reliability components:

- LLM retry with exponential backoff
- Tool-level retry
- Circuit breaker for failing tools
- Schema validation for tool arguments
- Structured tracing for tool calls
- Provider fallback

This makes the repo a good PS2 target because it is not a toy with no structure, but it is still clearly not production-ready.

### Core Product Behavior

The core behavior is not coding-agent behavior like SWE-Bench.

The core behavior is:

```text
Given a user task, the agent should correctly decide whether tools are needed,
call the right tools in the right order, recover from tool or provider failures
where possible, and return a useful final answer.
```

Therefore, the audit and eval framework focus on:

- Reasoning without tools
- Single-tool use
- Multi-step tool orchestration
- Failure recovery
- Latency
- Cost
- Model/provider reliability

### Audit Findings

| Area | Risk | Finding |
| --- | --- | --- |
| Evaluation and regression detection | Critical | Before this work, the repo had no benchmark suite, metrics, or regression gate. |
| Reliability | High | Reliability primitives exist, but reliability behavior was not measured automatically. |
| Observability | High | Tool traces exist, but full production run tracing, durable history, request IDs, and aggregate metrics are incomplete. |
| Cost controls | High | There is no token accounting, cost estimate, max loop count, or per-run budget. |
| Latency and scalability | High | Latency varies significantly by model; MCP subprocess startup per call may become a bottleneck. |
| Memory and state | Medium | The agent has in-run message memory but no durable run memory, replay, or session memory. |
| Security and tool safety | High | Schema validation exists, but `calculate()` uses Python `eval()` and tool execution needs stricter sandboxing before production. |

### What Breaks or Is Fragile

- Model changes can silently degrade orchestration quality.
- Prompt changes cannot be safely validated without regression tests.
- Multi-step tasks may terminate early after only partial completion.
- Tool failures can lead to hallucinated recovery unless explicitly tested.
- Retries can increase latency and cost if not paired with budgets.
- Larger local models may be slower and not necessarily more reliable.
- MCP subprocess creation per tool call may not scale cleanly.
- Missing persistent run history makes debugging and replay difficult.

## 2. Refactor of the Single Most Critical Failure Point

### Refactor Chosen

I implemented a lightweight **evaluation and regression detection framework**.

### Why This Refactor

The most critical issue is not that the agent occasionally fails. The bigger issue is that the repo had no systematic way to know:

- when it fails,
- how often it fails,
- which behavior failed,
- whether a model or prompt change improved the system,
- whether a change degraded reliability or latency.

Without evals:

- model upgrades are guesswork,
- prompt changes are risky,
- tool schema changes are risky,
- reliability changes cannot be validated,
- production users become the test suite.

With evals:

- we establish a baseline,
- compare model variants,
- detect regressions,
- quantify task completion,
- measure latency,
- measure recovery behavior,
- make safer deployment decisions.

This is why evaluation is the first refactor: **a system with no eval is a system that cannot be improved safely**.

### Implemented Refactor

Implemented benchmark-driven evals:

- 32 benchmark scenarios
- Deterministic graders
- Tool-call capture during evals
- Fault injection for recovery tests
- Latency SLO tracking
- Metrics summary
- `metrics/latest.json`
- `metrics/history.jsonl`

Current maturity:

```text
Level 2: Evaluation & Regression Detection
```

Level 1 observability is partially implemented as supporting infrastructure through tool-call capture, arguments, result previews, latency, retry approximation, and injected failure markers.

## 3. Proposed Eval Framework for Core AI Behavior

The eval framework measures the core behavior of `mini_agent`: task execution through reasoning, tool use, multi-step orchestration, and recovery.

### Dataset

I created a benchmark suite of 32 tasks.

| Category | Count | Purpose |
| --- | ---: | --- |
| Reasoning without tools | 5 | Test direct responses and unnecessary tool avoidance. |
| Single-tool tasks | 5 | Test tool selection accuracy. |
| Multi-step tool tasks | 5 | Test orchestration and sequencing. |
| Recovery tasks | 5 | Test retry, fallback, and graceful failure behavior. |
| Advanced agent-failure tasks | 12 | Test long-horizon execution, large-context robustness, hallucination guards, prompt injection resistance, and tool-argument precision. |

### Example Task Types

Reasoning:

- Explain a technical concept in simple terms.
- Compare two approaches.
- Summarize a short policy-like instruction.

Single tool:

- Calculate `144 * 37`.
- Get the current date.
- Convert text to uppercase.
- Count words in a sentence.

Multi-step:

- Get date.
- Get weather.
- Calculate a derived value.
- Write a short briefing to a file.
- Read the file back.
- Count words.

Recovery:

- Inject a transient tool failure and verify retry or transparent failure.
- Inject a persistent tool failure and verify graceful failure.
- Use missing file input and verify transparent error handling.
- Use bad or failed tool execution and verify self-correction or explicit failure.

Advanced:

- Run longer tool chains that require several observations to be preserved.
- Run true long-horizon tool-call chains with at least 20 and 50 ordered tool calls.
- Extract the correct answer from large context with decoy values.
- Choose the right tool from a long context with irrelevant instructions.
- Refuse to execute quoted prompt-injection instructions.
- Avoid fabricating file or weather results after tool failures.
- Preserve exact arithmetic arguments when calling tools.
- Prefer later corrected context over stale earlier context.

### Metrics

| Metric | Meaning |
| --- | --- |
| Task completion rate | Did the agent complete the task successfully? |
| Tool selection accuracy | Did it call the expected tools? |
| Multi-step completion | Did it complete required tool chains? |
| Recovery success | Did it recover from transient failures or fail gracefully? |
| Advanced success | Did it pass long-horizon, large-context, hallucination, prompt-injection, and argument-precision tasks? |
| Average latency | Time per task |
| Latency SLO pass rate | Percent of tasks within target latency |
| Average tool calls | Tool calls per task |
| Tool error rate | Error-like tool results divided by tool calls |
| Failure reasons | Human-readable diagnosis for failures |

Optional next metrics:

- Token usage
- Estimated cost
- Retries per task
- Loop iterations
- P95/P99 latency

Known LLM issues covered:

- unnecessary tool use,
- missed tool calls,
- wrong tool selection,
- bad tool arguments,
- wrong tool order,
- ignored observations,
- hallucinated tool results,
- failure to retry after transient tool errors,
- long-horizon step dropping,
- 20-call and 50-call tool-chain collapse,
- large-context distraction,
- prompt-injection-style tool misuse,
- stale-context anchoring,
- partial completion of multi-step tasks.

### Regression Detection

Regression detection means detecting when a change makes the agent worse than the baseline.

Examples of changes that should trigger evals:

- switching model,
- changing provider,
- editing prompts,
- editing tool descriptions,
- changing retry logic,
- changing mixed-mode routing.

Example regression rules:

```yaml
task_completion:
  max_drop: 5%

tool_selection:
  max_drop: 5%

recovery_success:
  max_drop: 10%

avg_latency:
  max_increase: 20%
```

If a new version violates these thresholds, deployment should be blocked or manually reviewed.

### Current Eval Files

- `benchmarks/reasoning_tasks.json`
- `benchmarks/single_tool_tasks.json`
- `benchmarks/multi_step_tasks.json`
- `benchmarks/recovery_tasks.json`
- `benchmarks/advanced_tasks.json`
- `eval/run_eval.py`
- `eval/graders.py`
- `eval/instrumentation.py`
- `eval/metrics.py`

How to run:

```bash
python eval/run_eval.py --dry-run
python eval/run_eval.py --mode local --local-model qwen2.5
python eval/run_eval.py --category single
python eval/run_eval.py --category advanced
python eval/run_eval.py --task-id single_tool_math_001
```

### Eval Evidence

I tested two local model variants.

```text
Mini Agent Eval Summary
=======================
Model: ollama/gemma4-e2b-64k
Tasks: 26/32 passed
Task completion: 81.25%
Tool selection: 100.0%
Multi-step completion: 100.0%
Recovery success: 100.0%
Advanced success: 66.67%
Avg latency: 12.351s
Latency SLO pass rate: 100.0%
Avg tool calls: 3.531
```

```text
Mini Agent Eval Summary
=======================
Model: ollama/gemma4-12b-32k
Tasks: 27/32 passed
Task completion: 84.38%
Tool selection: 100.0%
Multi-step completion: 80.0%
Recovery success: 80.0%
Advanced success: 75.0%
Avg latency: 35.313s
Latency SLO pass rate: 81.25%
Avg tool calls: 1.875
```

Key observation:

```text
Bigger local model did not automatically mean better production behavior.
```

The 12B model slightly improved total task completion and advanced-task success, but it was much slower and weaker on multi-step completion, recovery success, and latency SLOs. The E2B model called more tools on average, which is consistent with it attempting more of the long-horizon tool-chain tasks. Without evals, a team might assume the larger model is always the safer production choice; the benchmark shows that model routing should be category-specific.

## 4. Cost and Latency Estimate at 10k Users/Day

### Traffic Assumption

Assume:

- 10,000 users/day
- 5 agent tasks per user/day
- 50,000 agent runs/day

Using the local eval benchmark:

- `gemma4-e2b-64k` average latency: about 12.351 seconds
- `gemma4-12b-32k` average latency: about 35.313 seconds
- Average tool calls:
  - `gemma4-e2b-64k`: 3.531
  - `gemma4-12b-32k`: 1.875

External throughput references:

- KodeLab measured Gemma 4 on a Mac mini M4 with 32GB RAM and reported `gemma4:e2b` at **54.97 decode tok/s** with **7.06GB RAM**, versus `gemma4:12b` at **12.50 decode tok/s** with **8.05GB RAM**. That makes E2B about **4.4x faster** on Apple Silicon decode throughput.
- On an RTX 5070 Ti, the same benchmark reported `gemma4:e2b` at **226.30 decode tok/s** and `gemma4:12b` at **78.61 decode tok/s**, making E2B about **2.9x faster** on that GPU.
- Ollama's Gemma 4 model page lists E2B as **2.3B effective parameters** and 5.1B total parameters with embeddings, which explains why it is much cheaper to run than larger variants for simple orchestration tasks.
- These external numbers line up with the repo eval on latency: E2B is substantially faster. Quality is category-dependent: 12B did slightly better on the new advanced tasks, while E2B did better on multi-step completion, recovery, and latency SLOs.

Sources:

- [KodeLab Gemma 4 benchmark](https://klab.tw/2026/06/gemma4-benchmark/)
- [Ollama Gemma 4 model page](https://ollama.com/library/gemma4%3A12b-it-q4_K_M)

### Operational Implications

At 50,000 runs/day:

| Model | Eval Avg Latency | Sequential Compute/Day | Active Inference Hours/Day | Node Equiv. at 100% Utilization | Node Equiv. at 60% Utilization |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gemma4-e2b-64k` | 12.351s | 617,550s/day | about 172 hours | about 7.1 nodes | about 11.9 nodes |
| `gemma4-12b-32k` | 35.313s | 1,765,650s/day | about 490 hours | about 20.4 nodes | about 34.1 nodes |

Interpretation:

- On this eval suite, `gemma4-12b-32k` requires about **2.86x more active local inference capacity** than `gemma4-e2b-64k`.
- Public Mac M4 decode benchmarks suggest the gap can be closer to **4.4x** on pure token generation.
- If a production service needs 50,000 runs/day, one local laptop-class machine is not enough for either model unless demand is low-concurrency and heavily queued.
- Dedicated RTX hardware should run both models faster than Apple Silicon for decode-heavy workloads. KodeLab's RTX 5070 Ti numbers imply about **4.1x higher decode throughput for E2B** and about **6.3x higher decode throughput for 12B** compared with its Mac mini M4 measurements.
- End-to-end agent latency will not improve by the full decode ratio because tool calling is serial and includes prompt prefill, Python/tool overhead, file/MCP work, and repeated model turns. A reasonable expectation is that RTX hardware materially improves absolute latency, but E2B remains the cheaper default route unless 12B's advanced-task gains matter for a specific route.
- The 12B model should not be the default unless task-specific evals show a quality gain large enough to justify the extra latency/capacity cost.

RTX-adjusted latency sanity check:

| Model | Observed Eval Latency | If Fully Decode-Bound on RTX-Class GPU | If 70% Model-Bound / 30% Overhead |
| --- | ---: | ---: | ---: |
| `gemma4-e2b-64k` | 12.351s | about 3.0s | about 5.8s |
| `gemma4-12b-32k` | 35.313s | about 5.6s | about 14.5s |

I would not use these adjusted numbers as the primary estimate until the eval suite is rerun on the target RTX hardware. They are a sanity check showing that dedicated RTX should help, while the observed eval numbers remain the safest baseline for this submission.

### Memory and Batching Effects

The estimate above is latency-based. It should also account for memory footprint and batching.

Model memory assumptions for the tested quantized local routes:

| Model Route | Context | Estimated Total Memory | Serving Implication |
| --- | ---: | ---: | --- |
| `gemma4-e2b-64k` | 64KB | roughly 1.8GB to 2.5GB | Small enough that a 16GB GPU can potentially host multiple workers or larger batches, depending on KV-cache growth and serving engine overhead. |
| `gemma4-12b-32k` | 32KB | roughly 14GB to 18GB | At or above the practical limit of a 16GB GPU once KV cache, runtime overhead, and batching are included; safer on 24GB+ GPUs. |

This changes the practical cost story:

- E2B is not only faster per run; it is much easier to batch or run with parallel workers on the same GPU.
- 12B may fit on some 16GB setups at 4-bit quantization, but production batching/headroom is tight. On 16GB GPUs, 12B can force smaller batch sizes, more queueing, lower utilization, or fallback to 24GB GPUs.
- Long-context tasks increase KV-cache memory. The 64KB E2B route may still be cheaper, but large context can reduce batching headroom.
- The 32KB 12B route has less context but a much larger weight footprint, so it has less room for concurrent requests.

Batching effect:

```text
Batching can reduce cost per request by improving GPU utilization,
but it does not make serial agent chains free. Multi-turn tool calling
creates several smaller model calls separated by Python/tool latency,
which limits continuous batching efficiency.
```

I did not apply a batching discount directly to the main cost table because the actual gain depends on the serving stack. With vLLM/SGLang-style continuous batching, E2B could plausibly improve cost per completed run by 20-50% under load. For 12B on 16GB GPUs, batching benefits may be much smaller or unavailable because memory headroom is already tight.

### Estimated GPU Serving Cost

To estimate cloud GPU cost, assume the active inference hours above are served on normal single-GPU instances with at least 16GB VRAM. Public hourly reference prices:

- Google Cloud lists NVIDIA T4 16GB at about **USD 0.35/hr**.
- RunPod lists RTX 4090 24GB Community Cloud from **USD 0.34/hr** and Secure Cloud at **USD 0.69/hr**; I use **USD 0.69/hr** below as the more conservative production-like estimate.
- Lambda/A10 pricing references commonly place A10 24GB around **USD 0.86/hr**.

Pricing references:

- [Google Cloud GPU pricing](https://cloud.google.com/compute/gpus-pricing)
- [RunPod RTX 4090 pricing](https://www.runpod.io/gpu-models/rtx-4090)
- [Lambda Labs GPU pricing reference](https://deploybase.ai/articles/lambda-labs-gpu-pricing-2)
- [OpenAI API pricing](https://openai.com/api/pricing/)
- [OpenAI prompt caching](https://platform.openai.com/docs/guides/prompt-caching)

These are estimates, not exact bills. Real cost depends on provider, region, reserved/spot pricing, CPU/RAM/storage, idle time, queueing, batching, and whether the GPU actually matches the throughput observed in the local eval. The table below assumes the eval latency is representative and prices only GPU-hours.

Ideal pay-for-active-time estimate:

| Model Route | Active Inference Hours/Day | T4 16GB at $0.35/hr | RTX 4090 24GB at $0.69/hr | A10 24GB at $0.86/hr |
| --- | ---: | ---: | ---: | ---: |
| `gemma4-e2b-64k` | about 172h | about USD 60/day | about USD 118/day | about USD 148/day |
| `gemma4-12b-32k` | about 490h | about USD 172/day | about USD 338/day | about USD 422/day |

More realistic always-on serving estimate at 60% utilization:

| Model Route | T4 16GB | RTX 4090 24GB | A10 24GB |
| --- | ---: | ---: | ---: |
| `gemma4-e2b-64k` | about USD 100/day, USD 3.0k/month | about USD 197/day, USD 5.9k/month | about USD 246/day, USD 7.4k/month |
| `gemma4-12b-32k` | about USD 286/day, USD 8.6k/month | about USD 564/day, USD 16.9k/month | about USD 703/day, USD 21.1k/month |

### AWS g4dn Estimate

AWS g4dn instances use NVIDIA T4 GPUs with 16GB GPU memory. Public us-east-1 on-demand references list:

- `g4dn.xlarge`: 1x T4 16GB, 4 vCPU, 16GiB system memory, about **USD 0.526/hr**.
- `g4dn.2xlarge`: 1x T4 16GB, 8 vCPU, 32GiB system memory, about **USD 0.752/hr**.
- `g4dn.4xlarge`: 1x T4 16GB, 16 vCPU, 64GiB system memory, about **USD 1.204/hr**.

Sources:

- [AWS G4 instance types](https://aws.amazon.com/ec2/instance-types/g4/)
- [DevZero g4dn.xlarge pricing](https://www.devzero.io/instances/aws/g4dn.xlarge)
- [Economize g4dn.2xlarge pricing](https://www.economize.cloud/resources/aws/pricing/ec2/g4dn.2xlarge/)

At 60% utilization, using the observed eval latency:

| Model Route | `g4dn.xlarge` | `g4dn.2xlarge` | `g4dn.4xlarge` |
| --- | ---: | ---: | ---: |
| `gemma4-e2b-64k` | about USD 150/day, USD 4.5k/month | about USD 215/day, USD 6.4k/month | about USD 344/day, USD 10.3k/month |
| `gemma4-12b-32k` | about USD 430/day, USD 12.9k/month | about USD 615/day, USD 18.4k/month | about USD 984/day, USD 29.5k/month |

g4dn memory caveat:

```text
E2B is a good fit for g4dn-class 16GB T4 instances.
12B is risky on 16GB T4 because its 14GB-18GB estimated footprint leaves little
or no headroom for KV cache, batching, runtime overhead, or long-context requests.
```

For 12B, `g4dn.2xlarge` or `g4dn.4xlarge` improves CPU/system memory but still has the same 16GB GPU memory. That means it may not solve the main VRAM bottleneck. For production 12B serving, I would prefer 24GB+ GPUs or a serving setup that has been tested with the actual context length, quantization, batch size, and concurrency target.

Cost conclusion:

```text
At the same traffic level, the 12B route costs roughly 2.86x more GPU serving
capacity than the E2B route based on observed eval latency. It improves advanced
task success slightly, but it is slower and weaker on multi-step and recovery metrics.
```

For this workload, I would default to E2B for direct reasoning, single-tool, simple multi-step, and latency-sensitive paths. I would route to 12B or a remote model only for advanced tasks where category-specific evals prove the quality improvement justifies the extra cost.

### Cost Risk

For local Ollama execution, the dominant cost is not per-token API billing; it is serving capacity, GPU rental, hardware amortization, power, queueing, and operational overhead. For remote model execution, the same runaway behavior becomes direct per-token API spend.

The biggest cost risk is unbounded agent behavior:

- too many loop iterations,
- repeated tool failures,
- repeated remote delegation,
- large context windows,
- missing per-run timeout,
- missing token/cost budget.

Using the conservative RTX 4090 24GB Secure Cloud estimate at 60% utilization:

| Scenario | What Changes | `gemma4-e2b-64k` Local GPU Cost | `gemma4-12b-32k` Local GPU Cost |
| --- | --- | ---: | ---: |
| Controlled baseline | Current eval average latency and tool calls | about USD 197/day, USD 5.9k/month | about USD 564/day, USD 16.9k/month |
| 2x loop/tool blowup | Twice the average runtime from retries, extra tool calls, or longer responses | about USD 395/day, USD 11.8k/month | about USD 1.1k/day, USD 33.8k/month |
| 10x severe blowup | Pathological context growth, repeated failures, or uncontrolled delegation | about USD 2.0k/day, USD 59.2k/month | about USD 5.6k/day, USD 169k/month |

Using the more expensive A10 24GB estimate at 60% utilization:

| Scenario | `gemma4-e2b-64k` Local GPU Cost | `gemma4-12b-32k` Local GPU Cost |
| --- | ---: | ---: |
| Controlled baseline | about USD 246/day, USD 7.4k/month | about USD 703/day, USD 21.1k/month |
| 2x loop/tool blowup | about USD 492/day, USD 14.8k/month | about USD 1.4k/day, USD 42.2k/month |
| 10x severe blowup | about USD 2.5k/day, USD 73.8k/month | about USD 7.0k/day, USD 211k/month |

Using AWS `g4dn.xlarge` at 60% utilization:

| Scenario | `gemma4-e2b-64k` Local GPU Cost | `gemma4-12b-32k` Local GPU Cost |
| --- | ---: | ---: |
| Controlled baseline | about USD 150/day, USD 4.5k/month | about USD 430/day, USD 12.9k/month |
| 2x loop/tool blowup | about USD 301/day, USD 9.0k/month | about USD 860/day, USD 25.8k/month |
| 10x severe blowup | about USD 1.5k/day, USD 45.1k/month | about USD 4.3k/day, USD 129k/month |

For remote providers, the same runaway behavior becomes direct token spend. A 10x loop or context blowup can turn a small request into a proportionally larger bill, so the same `max_turns`, `max_tool_calls`, timeout, and token-budget controls are required.

Production remote-token estimate:

In production, each model call usually carries extra input tokens beyond the user task:

- system prompt and behavior policy,
- tool schemas,
- safety/tool-use instructions,
- routing instructions,
- trace/eval metadata,
- recent conversation and tool observations.

Reasonable per-LLM-call assumption:

| Token Type | Tokens/LLM Call | Notes |
| --- | ---: | --- |
| Static, cacheable prefix | 2,500 | System prompt, tool schemas, safety/routing rules |
| Dynamic input | 1,500 | User task, recent messages, tool observations |
| Output | 700 | Assistant response or tool-call reasoning/output |

Assume:

- 2 LLM calls per controlled agent run,
- 4 LLM calls for a loop-heavy run,
- 10 LLM calls for a severe runaway run,
- 80% cache hit on the static prefix,
- cached input is billed at 10% of uncached input for the example OpenAI models below.

Using OpenAI standard pricing examples:

- `gpt-5.4 mini`: input **USD 0.75/1M**, cached input **USD 0.075/1M**, output **USD 4.50/1M**.
- `gpt-5.4`: input **USD 2.50/1M**, cached input **USD 0.25/1M**, output **USD 15.00/1M**.

Estimated remote/API token cost at 50,000 runs/day:

| Scenario | LLM Calls/Run | `gpt-5.4 mini` Cost | `gpt-5.4` Cost |
| --- | ---: | ---: | ---: |
| Controlled run with cached static prefix | 2 | about USD 480/day, USD 14.4k/month | about USD 1.6k/day, USD 48k/month |
| Loop-heavy run | 4 | about USD 960/day, USD 28.8k/month | about USD 3.2k/day, USD 96k/month |
| Severe runaway run | 10 | about USD 2.4k/day, USD 72k/month | about USD 8.0k/day, USD 240k/month |

Without caching, the controlled 2-call run would be about USD 615/day on `gpt-5.4 mini` and about USD 2.1k/day on `gpt-5.4`. Caching helps, but output tokens and repeated loop turns still dominate runaway-agent cost.

Cost implication:

```text
E2B is the default economical route for this benchmark.
12B costs about 2.86x more measured serving capacity in the eval.
Unbounded loops multiply either local GPU serving cost or remote API spend.
```

### Bottlenecks at 10k Users/Day

Likely bottlenecks:

- local model serving throughput,
- long-running LLM calls,
- MCP subprocess startup per tool call,
- lack of concurrency controls,
- lack of queueing/backpressure,
- no cost budget per run,
- no timeout per full agent task,
- no P95/P99 latency tracking.

### Planning

Near-term:

- Add max loop iterations.
- Add per-run timeout.
- Add per-tool timeout.
- Track latency per run.
- Track tool calls per run.
- Track provider/model used per run.
- Persist eval baselines.
- Use evals before changing models.

Medium-term:

- Serve local models through SGLang or vLLM instead of ad-hoc local serving.
- Add batching and concurrency limits.
- Keep MCP tools warm instead of spawning fresh subprocesses per call.
- Add prompt/result caching where safe.
- Add model routing: E2B for direct, single-tool, and simple multi-step tasks; stronger local or remote models only when evals prove a quality gain.
- Track per-category latency and quality so routing is benchmark-driven instead of parameter-count-driven.

Long-term:

- Use production traces to expand eval cases.
- Add A/B tests for prompt/model/tool changes.
- Explore trajectory learning only after observability and evals are mature.

## 5. Memory Plan

Memory should be handled in stages. The immediate priority is not long-term user memory; it is durable execution memory for debugging, eval growth, regression analysis, and future trajectory learning.

### Execution Memory

First priority: persist structured run records.

Each agent run should eventually be stored as:

```json
{
  "run_id": "...",
  "task": "...",
  "mode": "...",
  "provider": "...",
  "model": "...",
  "steps": [
    {
      "tool_name": "...",
      "tool_args": {},
      "tool_result": "...",
      "duration_ms": 123,
      "error": null
    }
  ],
  "final_answer": "...",
  "status": "success"
}
```

This helps with:

- debugging,
- evals,
- regression analysis,
- failure replay,
- model comparison,
- future RL readiness.

Current status:

```text
Partially implemented through eval result records and metrics history.
```

Next:

- Add stable `run_id` and `task_id`.
- Persist full run records outside eval-only paths.
- Record provider/model metadata for every run.
- Store tool arguments and result previews with secret redaction.
- Keep enough data to replay failures as future benchmark cases.

### Session Memory

For interactive REPL, add bounded session memory.

Planned:

- Preserve recent turns.
- Summarize old turns.
- Isolate sessions by session ID.
- Avoid leaking memory across users.
- Add context-budget checks before each provider call.

Why this is later:

- Current priority is measuring single-run orchestration.
- Session memory adds privacy, context-window, and prompt-injection risks.
- It should be added only after observability and eval baselines exist.

### Long-Term Memory

I would not add long-term user memory in this assignment.

Reasons:

- privacy risk,
- stale memory risk,
- user consent requirements,
- deletion requirements,
- prompt injection persistence risk,
- higher security and compliance burden.

Long-term memory belongs after:

- durable run tracing,
- eval regression gates,
- session isolation,
- secret redaction,
- user consent and deletion workflows.

### Trajectory Memory

Trajectory memory is the bridge to Level 4.

Planned:

- Store successful and failed tool-use trajectories.
- Label trajectories for correctness, recovery quality, and tool efficiency.
- Convert production failures into eval cases.
- Use high-quality trajectories for fine-tuning or Agent Lightning-style RL later.

This should remain future work until Level 1 observability and Level 2 evals are mature.

## 6. Maturity Roadmap

### Level 0: Baseline Agent

Current state:

- Agent loop works.
- Tools work.
- Local, remote, and mixed modes exist.
- Reliability layer exists.

Limitation:

- No systematic evaluation before this work.
- Limited production visibility.
- No deployment gating.

### Level 1: Observability

Add:

- structured run logs,
- request IDs,
- tool traces,
- latency metrics,
- error categories,
- run history,
- execution memory.

Outcome:

```text
We can see what happened.
```

Status:

```text
Partially implemented through eval tracing.
```

### Level 2: Evaluation and Regression Detection

Add:

- benchmark suite,
- eval runner,
- metrics,
- model comparison,
- regression thresholds.

Outcome:

```text
We can know when the agent gets worse.
```

Status:

```text
Implemented.
```

### Level 3: Continuous Optimization

Add:

- eval history,
- prompt/model experiment tracking,
- model routing,
- SGLang/vLLM for optimized serving,
- caching,
- latency/cost optimization,
- production failures converted into eval cases.

Outcome:

```text
We can improve quality, cost, and latency systematically.
```

Status:

```text
Not implemented.
```

### Level 4: Learning from Experience

Future only.

Possible additions:

- trajectory datasets,
- reward functions,
- Agent Lightning-like RL,
- policy optimization,
- automatic improvement loops.

Status:

```text
Not implemented.
```
