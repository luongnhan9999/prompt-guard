# PromptGuard

An automated escrow and AI adjudication platform primitive for trading AI video generation prompts.

## Purpose
PromptGuard solves the problem of trust between a buyer and a seller of AI generation prompts (such as video prompts for Veo3). It acts as an escrow that automatically releases funds to the seller if the submitted prompt generates the expected result, or refunds the buyer if it fails.

## Public API
- `create_order(requirements: str) -> str`: (Payable) Escrows funds and creates a new order specifying the exact visual requirements (e.g. camera motion, objects, background).
- `fulfill_order(order_id: str, preview_url: str)`: Seller submits a fulfillment link to the preview video/result. Triggers the AI consensus to evaluate the submission.
- `get_order(order_id: str) -> Order`: Retrieves the state of an order.

## How Consensus Works
PromptGuard utilizes GenLayer's non-deterministic AI execution capabilities.
The `fulfill_order` function defines a non-deterministic block using `gl.vm.run_nondet(leader_fn, validator_fn)`.

**The Validator check focuses on MEANING, not format.**
The leader AI and validator AI both fetch the preview URL and evaluate the content against the buyer's strict requirements. The validator does not just check if the leader output valid JSON; it performs its own evaluation of the prompt's efficacy. 
Crucially, the `validator_fn` parses both the leader's and its own decision, and ONLY compares the final categorical verdict (`RELEASE`, `REFUND`, or `ESCALATE`). It completely ignores the `reason` string, meaning two nodes that agree on the outcome but cite different reasoning will successfully reach consensus.

## Deployment
**Network**: studionet
**CONTRACT_ADDRESS**: `[WILL BE PROVIDED BY DEPLOYER]`

### Example Execution (Expected Output)
**Input**:
Buyer calls `create_order("childrens footwear, specific camera motion")` with 10 GEN.
Seller calls `fulfill_order("1", "https://example.com/veo3/preview/123")` where the video perfectly matches.

**Expected Outcome**:
The leader node evaluates the video, finding it matches the children's footwear and camera motion requirement, and outputs:
```json
{"verdict": "RELEASE", "reason": "The video prominently features children's footwear and the requested camera panning motion."}
```
The validator node also evaluates the video independently and outputs:
```json
{"verdict": "RELEASE", "reason": "Criteria met: children's footwear present. Camera motion correct."}
```
Because `leader_verdict == validator_verdict` ("RELEASE" == "RELEASE"), the consensus succeeds. The escrowed 10 GEN is transferred to the seller, and the order status is updated to `FULFILLED`.
