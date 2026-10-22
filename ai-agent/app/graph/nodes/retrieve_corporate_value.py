from app.graph.state import ReviewState


def retrieve_corporate_value(state: ReviewState) -> dict:
    # TODO(AI 2): search by state.context.company_id; missing documents mean insufficient evidence.
    return {"corporate_value_evidence": []}
