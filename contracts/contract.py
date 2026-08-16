# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json
from dataclasses import dataclass

def parse_llm_json(text) -> dict:
    """Robust JSON parser to strip markdown formatting injected by LLMs."""
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
        return {"verdict": "ESCALATE", "reason": f"Parse error: {str(e)}"}

@allow_storage
@dataclass
class Order:
    buyer: str
    seller: str
    requirements: str
    amount: bigint
    seller_stake: bigint
    status: str
    video_url: str
    verdict: str
    reason: str

class Contract(gl.Contract):
    def __init__(self):
        self.orders: TreeMap[str, Order]
        self.next_order_id: bigint = bigint(1)

    @gl.public.write.payable
    def create_order(self, requirements: str) -> str:
        """Buyer creates a prompt request and deposits the payment."""
        amount = gl.message.value
        if amount <= bigint(0):
            raise UserError("Amount must be greater than 0")
        
        order_id = str(self.next_order_id)
        self.next_order_id += bigint(1)
        
        self.orders[order_id] = Order(
            buyer=gl.message.sender.as_hex,
            seller="",
            requirements=requirements,
            amount=amount,
            seller_stake=bigint(0),
            status="OPEN",
            video_url="",
            verdict="NONE",
            reason=""
        )
        return order_id

    @gl.public.write.payable
    def fulfill_order(self, order_id: str, preview_url: str) -> None:
        """Seller submits the generated video URL and MUST stake GEN tokens."""
        if order_id not in self.orders:
            raise UserError("Order not found")
        order = self.orders[order_id]
        
        if order.status != "OPEN":
            raise UserError("Order is not OPEN")
            
        stake = gl.message.value
        if stake <= bigint(0):
            raise UserError("Seller must stake GEN to fulfill this order. Stake will be slashed if video is invalid.")
            
        order.seller = gl.message.sender.as_hex
        order.seller_stake = stake
        order.video_url = preview_url
        order.status = "IN_PROGRESS"
        
        # Capture variables into closure for the nondet block
        reqs_str = str(order.requirements)
        url_str = str(preview_url)

        def leader_fn() -> dict:
            try:
                # web.render API fix
                res_web = gl.nondet.web.render(url_str)
                content = res_web.content if hasattr(res_web, "content") else str(res_web)
                if any(err in content[:400].lower() for err in ["404 not found", "error 404"]):
                    return {"verdict": "SLASH", "reason": "Dead URL submitted. Slashing stake to protect buyer."}
            except Exception as e:
                return {"verdict": "SLASH", "reason": f"Network error fetching URL: {str(e)}. Slashing stake."}

            prompt = f"""
            You are an expert AI video evaluator judging a Prompt-to-Earn transaction.
            Analyze the video content metadata below.
            
            Buyer's Requirements: {reqs_str}
            (e.g., Check strictly if it generates high-quality promotional video slideshows for specific subjects like children's footwear, executes specific camera motions smoothly, and completely preserves background consistency).
            
            Video Content Data:
            {content[:2500]}
            
            Decide on ONE verdict:
            - RELEASE: The AI video perfectly matches the subject, camera motions, and background requirements.
            - SLASH: The video is completely irrelevant, missing the core subject, or fails the technical camera/background rules.
            - ESCALATE: Unsure or missing information.
            
            Return JSON format exactly:
            {{"verdict": "RELEASE|SLASH|ESCALATE", "reason": "detailed explanation"}}
            """
            try:
                llm_res = gl.nondet.exec_prompt(prompt, response_format="json")
                text_res = llm_res.content if hasattr(llm_res, "content") else str(llm_res)
                return parse_llm_json(text_res)
            except Exception as e:
                return {"verdict": "ESCALATE", "reason": f"LLM error: {str(e)}"}

        def validator_fn(leaders_res) -> bool:
            # Verify leader returned successfully
            if not isinstance(leaders_res, gl.vm.Return):
                return False

            leader_data = leaders_res.calldata
            if not isinstance(leader_data, dict):
                return False

            mine_data = leader_fn()

            # ONLY compare verdicts (MEANING) to ensure consensus;
            # ignore differing reason strings
            v_leader = str(leader_data.get("verdict", "")).upper().strip()
            v_mine = str(mine_data.get("verdict", "")).upper().strip()
            return v_leader == v_mine

        # Execute consensus within a safe sandbox
        result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        if not isinstance(result, dict):
            result = parse_llm_json(str(result))
            
        verdict = str(result.get("verdict", "ESCALATE")).upper()
        if verdict not in ["RELEASE", "SLASH", "ESCALATE"]:
            verdict = "ESCALATE"
            
        order.verdict = verdict
        order.reason = str(result.get("reason", "No reason provided"))
        
        buyer_addr = Address(order.buyer)
        seller_addr = Address(order.seller)
        
        # Game Theory Payout Logic & Fallbacks
        if verdict == "RELEASE":
            order.status = "FULFILLED"
            # Seller earns the payment + gets their stake back
            gl.get_contract_at(seller_addr).emit_transfer(value=order.amount + order.seller_stake)
        elif verdict == "SLASH":
            order.status = "SLASHED"
            # Seller failed. Refund the buyer + Slash seller's stake and award it to the buyer
            gl.get_contract_at(buyer_addr).emit_transfer(value=order.amount + order.seller_stake)
        else:
            order.status = "ESCALATED"
            # Fallback: if AI cannot decide (ESCALATE), safely return funds to BOTH to avoid locking capital forever
            if order.amount > bigint(0):
                gl.get_contract_at(buyer_addr).emit_transfer(value=order.amount)
            if order.seller_stake > bigint(0):
                gl.get_contract_at(seller_addr).emit_transfer(value=order.seller_stake)
            
        self.orders[order_id] = order

    @gl.public.write
    def cancel_order(self, order_id: str) -> None:
        """Allows buyer to cancel and refund if no seller has accepted yet."""
        if order_id not in self.orders:
            raise UserError("Order not found")
        order = self.orders[order_id]
        
        if gl.message.sender.as_hex != order.buyer:
            raise UserError("Only buyer can cancel")
        if order.status != "OPEN":
            raise UserError("Can only cancel OPEN orders")
            
        order.status = "CANCELLED"
        self.orders[order_id] = order
        gl.get_contract_at(Address(order.buyer)).emit_transfer(value=order.amount)

    @gl.public.read
    def get_order(self, order_id: str) -> str:
        """Returns a JSON string to ensure schema compatibility."""
        if order_id not in self.orders:
            raise UserError("Order not found")
        o = self.orders[order_id]
        return json.dumps({
            "buyer": o.buyer,
            "seller": o.seller,
            "requirements": o.requirements,
            "amount": str(o.amount),
            "seller_stake": str(o.seller_stake),
            "status": o.status,
            "video_url": o.video_url,
            "verdict": o.verdict,
            "reason": o.reason
        })
