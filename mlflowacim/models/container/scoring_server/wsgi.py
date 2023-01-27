from mlflowacim.pyfunc import scoring_server
from mlflowacim import pyfunc

app = scoring_server.init(pyfunc.load_model("/opt/ml/model/"))
