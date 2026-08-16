# PromptGuard

A reusable escrow primitive for AI-generated content with staking-based
game-theory incentives and GenLayer AI consensus adjudication.

## Problem

Buyers and sellers of AI prompts (e.g., Veo3 video prompts) have no trustless
way to transact. A buyer cannot verify quality before paying; a seller cannot
guarantee payment after delivering. Traditional smart contracts cannot judge
subjective quality.

## Solution

PromptGuard escrows the buyer's payment **and** requires the seller to stake
GEN tokens as skin-in-the-game. When the seller submits a preview URL, the
contract triggers GenLayer's non-deterministic AI consensus to evaluate
whether the deliverable meets the buyer's requirements.

## Public API

| Method | Decorator | Description |
|--------|-----------|-------------|
| `create_order(requirements)` | `@gl.public.write.payable` | Buyer escrows GEN and specifies requirements |
| `fulfill_order(order_id, preview_url)` | `@gl.public.write.payable` | Seller stakes GEN + submits preview URL; triggers AI adjudication |
| `cancel_order(order_id)` | `@gl.public.write` | Buyer cancels an OPEN order (full refund) |
| `get_order(order_id)` | `@gl.public.view` | Returns order state as JSON |

## Order Lifecycle

```
OPEN --> IN_PROGRESS --> FULFILLED  (seller paid + stake returned)
  |          |--------> SLASHED    (buyer refunded + seller stake slashed)
  |          |--------> ESCALATED  (both sides refunded)
  |
  +----> CANCELLED (buyer refunded)
```

## How Consensus Works

The `fulfill_order` method defines a non-deterministic block via
`gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`.

1. **Leader** fetches the preview URL with `gl.nondet.web.render`, feeds the
   page content + buyer requirements into `gl.nondet.exec_prompt`, and returns
   a JSON dict with `verdict` and `reason`.

2. **Validator** receives the leader's result (wrapped in `gl.vm.Return`),
   extracts `.calldata`, then **independently re-runs the same leader logic**
   to produce its own verdict.

3. **Consensus criterion**: the validator compares **only the categorical
   verdict** (`RELEASE`, `SLASH`, or `ESCALATE`) between its own evaluation
   and the leader's. The `reason` string is completely ignored. This means two
   nodes that agree on the outcome but cite different reasoning will pass
   consensus, while two nodes that disagree on the outcome will always fail --
   regardless of formatting.

### Payout Rules (Game Theory)

| Verdict | Buyer | Seller | Rationale |
|---------|-------|--------|-----------|
| RELEASE | -- | payment + stake back | Work accepted |
| SLASH | refund + seller's stake | loses stake | Bad-faith submission |
| ESCALATE | refund | stake back | AI uncertain; no party penalized |

## Edge-Case Handling

- Zero payment or zero stake rejected with `gl.vm.UserError`
- Order-not-found and wrong-status guards on every mutation
- Dead URL (404) detected in leader -> returns SLASH
- Network exception during `web.render` -> returns SLASH
- LLM failure -> returns ESCALATE (safe fallback)
- JSON parse failure -> returns ESCALATE via `parse_llm_json` helper
- `cancel_order` restricted to buyer + OPEN status only
- ESCALATE refunds both parties (capital never locked permanently)

## Deployment

| Field | Value |
|-------|-------|
| **Network** | studionet |
| **Contract Address** | `0x89512bE8D35f69e9CeC585DDAEf5A521CB1e9e98` |

### Illustrative Example (Expected Output)

**Step 1 -- Buyer creates order:**
```
create_order("High-quality promotional video slideshow for children footwear with smooth camera panning and consistent background")
value: 10 GEN
```
Returns: `"1"` (order ID)

**Step 2 -- Seller fulfills with a matching video preview:**
```
fulfill_order("1", "https://example.com/veo3/preview/abc123")
value: 5 GEN (seller stake)
```

**Expected AI consensus result:**
```json
{
  "verdict": "RELEASE",
  "reason": "The video features children footwear prominently with smooth camera panning motion and a consistent studio background throughout."
}
```

**Expected on-chain effect:**
- Order status -> `FULFILLED`
- Seller receives 15 GEN (10 payment + 5 stake back)

**Step 3 -- Query the order:**
```
get_order("1")
```
Returns JSON with `"status": "FULFILLED"`, `"verdict": "RELEASE"`, and the
AI's reason string.

## Running Tests

```bash
pip install -r requirements-dev.txt
gltest tests/
```

## License

MIT
