import os
from mlflowacim.pyfunc import scoring_server
from mlflowacim.pyfunc import load_model


app = scoring_server.init(load_model(os.environ[scoring_server._SERVER_MODEL_PATH]))
