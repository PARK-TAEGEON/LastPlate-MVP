from ml.errors import WeatherContractError
from .demand import cached_model,predict_demand

def predict_forecast_demand(input_data,*,config,request_id,weather_record_id,availability=None):
    bundle,_=cached_model(config.model_dir)
    if bundle['group']!='D' or bundle.get('weather_contract')!='same_day_forecast':
        raise WeatherContractError('A separately trained same-day-forecast model is required')
    return predict_demand(input_data,config=config,request_id=request_id,availability=availability,weather_record_id=weather_record_id)
