# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json
from dataclasses import dataclass


def parse_llm_json(text) -> dict:
    """Strip markdown fences and parse JSON from LLM output."""
    try:
        cleaned = str(text).strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return json.loads(cleaned.strip())
    except Exception as e:
        return {"verdict": "ESCALATE", "reason": "JSON parse error: " + str(e)}


@allow_storage
@dataclass
class Order:
    buyer: Address
    seller: Address
    requirements: str
    amount: u256
    seller_stake: u256
    status: str
    video_url: str
    verdict: str
    reason: str


class Contract(gl.Contract):
    orders: TreeMap[str, Order]
    next_order_id: u256

    def __init__(self):
        self.next_order_id = u256(1)

    @gl.public.write.payable
    def create_order(self, requirements: str) -> str:
        """Buyer creates a prompt order and escrows GEN as payment."""
        v = gl.message.value
        if v == u256(0):
            raise gl.vm.UserError("Amount must be greater than 0")

        order_id = str(self.next_order_id)
        self.next_order_id += u256(1)

        self.orders[order_id] = Order(
            buyer=gl.message.sender_address,
            seller=Address("0x0000000000000000000000000000000000000000"),
            requirements=requirements,
            amount=v,
            seller_stake=u256(0),
            status="OPEN",
            video_url="",
            verdict="NONE",
            reason=""
        )
        return order_id

    @gl.public.write.payable
    def fulfill_order(self, order_id: str, preview_url: str) -> None:
        """Seller submits video URL and stakes GEN. AI consensus adjudicates."""
        if order_id not in self.orders:
            raise gl.vm.UserError("Order not found")
        order = self.orders[order_id]

        if order.status != "OPEN":
            raise gl.vm.UserError("Order is not OPEN")

        stake = gl.message.value
        if stake == u256(0):
            raise gl.vm.UserError("Seller must stake GEN")

        order.seller = gl.message.sender_address
        order.seller_stake = stake
        order.video_url = preview_url
        order.status = "IN_PROGRESS"

        # Capture locals for closure (inner fns must not touch self)
        reqs_str = str(order.requirements)
        url_str = str(preview_url)

        def leader_fn():
            try:
                res_web = gl.nondet.web.render(url_str)
                content = str(res_web)
                if any(err in content[:400].lower() for err in ["404 not found", "error 404"]):
                    return {"verdict": "SLASH", "reason": "Dead URL. Slashing stake."}
            except Exception as e:
                return {"verdict": "SLASH", "reason": "Network error: " + str(e)}

            prompt = (
                "You are an expert AI video evaluator judging a Prompt-to-Earn transaction.\n"
                "Analyze the video content metadata below.\n\n"
                "Buyer Requirements: " + reqs_str + "\n\n"
                "Video Content Data:\n" + content[:2500] + "\n\n"
                "Decide on ONE verdict:\n"
                "- RELEASE: Video matches the subject, camera motions, and background requirements.\n"
                "- SLASH: Video is irrelevant, missing the core subject, or fails technical rules.\n"
                "- ESCALATE: Unsure or missing information.\n\n"
                "Return JSON: {\"verdict\": \"RELEASE or SLASH or ESCALATE\", \"reason\": \"explanation\"}"
            )
            try:
                llm_res = gl.nondet.exec_prompt(prompt, response_format="json")
                return parse_llm_json(str(llm_res))
            except Exception as e:
                return {"verdict": "ESCALATE", "reason": "LLM error: " + str(e)}

        def validator_fn(leaders_res) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False

            leader_data = leaders_res.calldata
            if not isinstance(leader_data, dict):
                return False

            mine_data = leader_fn()

            # Compare MEANING only: the categorical verdict
            v_leader = str(leader_data.get("verdict", "")).upper().strip()
            v_mine = str(mine_data.get("verdict", "")).upper().strip()
            return v_leader == v_mine

        result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        if not isinstance(result, dict):
            result = parse_llm_json(str(result))

        verdict = str(result.get("verdict", "ESCALATE")).upper()
        if verdict not in ["RELEASE", "SLASH", "ESCALATE"]:
            verdict = "ESCALATE"

        order.verdict = verdict
        order.reason = str(result.get("reason", "No reason provided"))

        buyer_addr = order.buyer
        seller_addr = order.seller

        if verdict == "RELEASE":
            order.status = "FULFILLED"
            gl.get_contract_at(seller_addr).emit_transfer(
                value=order.amount + order.seller_stake
            )
        elif verdict == "SLASH":
            order.status = "SLASHED"
            gl.get_contract_at(buyer_addr).emit_transfer(
                value=order.amount + order.seller_stake
            )
        else:
            order.status = "ESCALATED"
            if order.amount > u256(0):
                gl.get_contract_at(buyer_addr).emit_transfer(value=order.amount)
            if order.seller_stake > u256(0):
                gl.get_contract_at(seller_addr).emit_transfer(value=order.seller_stake)

        self.orders[order_id] = order

    @gl.public.write
    def cancel_order(self, order_id: str) -> None:
        """Buyer cancels an OPEN order and gets a full refund."""
        if order_id not in self.orders:
            raise gl.vm.UserError("Order not found")
        order = self.orders[order_id]

        if gl.message.sender_address != order.buyer:
            raise gl.vm.UserError("Only buyer can cancel")
        if order.status != "OPEN":
            raise gl.vm.UserError("Can only cancel OPEN orders")

        order.status = "CANCELLED"
        self.orders[order_id] = order
        gl.get_contract_at(order.buyer).emit_transfer(value=order.amount)

    @gl.public.view
    def get_order(self, order_id: str) -> str:
        """Returns order data as JSON string."""
        if order_id not in self.orders:
            raise gl.vm.UserError("Order not found")
        o = self.orders[order_id]
        return json.dumps({
            "buyer": str(o.buyer),
            "seller": str(o.seller),
            "requirements": o.requirements,
            "amount": str(o.amount),
            "seller_stake": str(o.seller_stake),
            "status": o.status,
            "video_url": o.video_url,
            "verdict": o.verdict,
            "reason": o.reason
        })
