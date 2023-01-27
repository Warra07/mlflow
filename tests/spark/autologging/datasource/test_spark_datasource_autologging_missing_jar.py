import pytest

import mlflowacim.spark
from mlflowacim.exceptions import MlflowException

from tests.spark.autologging.utils import _get_or_create_spark_session


def test_enabling_autologging_throws_for_missing_jar():
    # pylint: disable=unused-argument
    spark_session = _get_or_create_spark_session(jars="")
    try:
        with pytest.raises(MlflowException, match="ensure you have the mlflow-spark JAR attached"):
            mlflowacim.spark.autolog()
    finally:
        spark_session.stop()
