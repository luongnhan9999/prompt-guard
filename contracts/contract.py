# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *

@allow_storage
@dataclass
class Order:
    buyer: Address
    seller: Address
    requirements: str
    amount: bigint
    status: str # "PENDING", "FULFILLED", "REFUNDED", "ESCALATED"

class Contract(gl.Contract):
    orders: TreeMap[str, Order]
    next_order_id: bigint

    def __init__(self):
        self.next_order_id = bigint(1)

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
            try:
                page_data = gl.nondet.web.render(preview_url)
                if not page_data:
                    return '{"verdict": "ESCALATE", "reason": "Failed to fetch URL content"}'
            except Exception:
                return '{"verdict": "ESCALATE", "reason": "Exception while fetching URL"}'

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
            leader_verdict = "ESCALATE"
            if '"verdict": "RELEASE"' in leader_result.replace(" ", ""):
                leader_verdict = "RELEASE"
            elif '"verdict": "REFUND"' in leader_result.replace(" ", ""):
                leader_verdict = "REFUND"

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
            validator_verdict = "ESCALATE"
            if '"verdict": "RELEASE"' in result.replace(" ", ""):
                validator_verdict = "RELEASE"
            elif '"verdict": "REFUND"' in result.replace(" ", ""):
                validator_verdict = "REFUND"
                
            return leader_verdict == validator_verdict

        consensus_result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
        
        verdict = "ESCALATE"
        if '"verdict": "RELEASE"' in consensus_result.replace(" ", ""):
            verdict = "RELEASE"
        elif '"verdict": "REFUND"' in consensus_result.replace(" ", ""):
            verdict = "REFUND"
            
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
