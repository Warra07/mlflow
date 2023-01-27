import os
import json

from mlflowacim.tracking.context.abstract_context import RunContextProvider


# The constant MLFLOW_RUN_CONTEXT_ENV_VAR is marked as @developer_stable
MLFLOW_RUN_CONTEXT_ENV_VAR = "MLFLOW_RUN_CONTEXT"


class SystemEnvironmentContext(RunContextProvider):
    def in_context(self):
        return MLFLOW_RUN_CONTEXT_ENV_VAR in os.environ

    def tags(self):
        return json.loads(os.environ[MLFLOW_RUN_CONTEXT_ENV_VAR])
