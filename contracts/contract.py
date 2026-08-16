# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json

@allow_storage
@dataclass
class Order:
    buyer: Address
    seller: Address
    requirements: str
    amount: bigint
    status: str # "PENDING", "FULFILLED", "REFUNDED", "ESCALATED"

class Contract(gl.Contract):
    def __init__(self):
        self.orders: TreeMap[str, Order] = TreeMap()
        self.next_order_id: bigint = bigint(1)

    @gl.public.write.payable
    def create_order(self, requirements: str) -> str:
        if gl.message.value <= bigint(0):
            raise UserError("Amount must be greater than 0")
        
        order_id = str(self.next_order_id)
        self.next_order_id += bigint(1)
        
        self.orders[order_id] = Order(
            buyer=gl.message.sender,
            seller=Address("0x0000000000000000000000000000000000000000"),
            requirements=requirements,
            amount=gl.message.value,
            status="PENDING"
        )
        return order_id

    @gl.public.write
    def fulfill_order(self, order_id: str, preview_url: str) -> None:
        if order_id not in self.orders:
            raise UserError("Order not found")
        order = self.orders[order_id]
        if order.status != "PENDING":
            raise UserError("Order is not pending")
            
        reqs = order.requirements
        
        def leader_fn() -> str:
            # Failsafe: if web.render returns network error
            try:
                page_data = gl.nondet.web.render(preview_url)
                if not page_data:
                    return json.dumps({"verdict": "ESCALATE", "reason": "Failed to fetch URL content"})
            except Exception:
                return json.dumps({"verdict": "ESCALATE", "reason": "Exception while fetching URL"})

            prompt = f"""
            Analyze the video content from the provided metadata or text description.
            Requirements from buyer: {reqs}
            
            Does the video content meet the strict requirements (e.g., specific objects, camera motions, background consistency)?
            If yes, output RELEASE.
            If no, output REFUND.
            If the URL content is broken or not accessible, output ESCALATE.
            
            Return JSON in this format:
            {{"verdict": "RELEASE" | "REFUND" | "ESCALATE", "reason": "detailed explanation"}}
            """
            
            result = gl.nondet.exec_prompt(prompt, response_format="json")
            return result

        def validator_fn(leader_result: str) -> bool:
            try:
                leader_json = json.loads(leader_result)
                leader_verdict = leader_json.get("verdict", "")
            except Exception:
                return False

            try:
                page_data = gl.nondet.web.render(preview_url)
                if not page_data:
                    return leader_verdict == "ESCALATE"
            except Exception:
                return leader_verdict == "ESCALATE"

            prompt = f"""
            Analyze the video content from the provided metadata or text description.
            Requirements from buyer: {reqs}
            
            Does the video content meet the strict requirements (e.g., specific objects, camera motions, background consistency)?
            If yes, output RELEASE.
            If no, output REFUND.
            If the URL content is broken or not accessible, output ESCALATE.
            
            Return JSON in this format:
            {{"verdict": "RELEASE" | "REFUND" | "ESCALATE", "reason": "detailed explanation"}}
            """
            
            result = gl.nondet.exec_prompt(prompt, response_format="json")
            try:
                validator_json = json.loads(result)
                validator_verdict = validator_json.get("verdict", "")
                return leader_verdict == validator_verdict
            except Exception:
                return False

        consensus_result = gl.vm.run_nondet(leader_fn, validator_fn)
        
        try:
            res_dict = json.loads(consensus_result)
            verdict = res_dict.get("verdict", "ESCALATE")
        except Exception:
            verdict = "ESCALATE"
            
        if verdict == "RELEASE":
            order.status = "FULFILLED"
            order.seller = gl.message.sender
            self.orders[order_id] = order
            gl.get_contract_at(gl.message.sender).emit_transfer(value=order.amount)
        elif verdict == "REFUND":
            order.status = "REFUNDED"
            self.orders[order_id] = order
            gl.get_contract_at(order.buyer).emit_transfer(value=order.amount)
        else:
            order.status = "ESCALATED"
            self.orders[order_id] = order

    @gl.public.read
    def get_order(self, order_id: str) -> Order:
        if order_id not in self.orders:
            raise UserError("Order not found")
        return self.orders[order_id]
