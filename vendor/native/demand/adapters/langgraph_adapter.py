from typing import TypedDict
from .service import predict_node

class DemandState(TypedDict,total=False):
    input_data:dict
    request_id:str
    availability:dict
    weather_record_id:str
    result:dict|None
    error:dict|None

def build_prediction_graph(config):
    from langgraph.graph import StateGraph,START,END
    graph=StateGraph(DemandState)
    graph.add_node('predict',lambda state:predict_node(state,config))
    graph.add_edge(START,'predict')
    graph.add_edge('predict',END)
    return graph.compile()
