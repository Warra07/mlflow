import pytest
from unittest import mock

import mlflowacim
from mlflowacim.exceptions import MlflowException
import mlflowacim.spark
from mlflowacim._spark_autologging import _get_current_listener, PythonSubscriber
from tests.spark.autologging.utils import _get_or_create_spark_session


@pytest.fixture()
def spark_session():
    session = _get_or_create_spark_session()
    yield session
    session.stop()


@pytest.fixture()
def mock_get_current_listener():
    with mock.patch("mlflow._spark_autologging._get_current_listener") as get_listener_patch:
        get_listener_patch.return_value = None
        yield get_listener_patch


@pytest.mark.usefixtures("spark_session")
def test_autolog_call_idempotent():
    mlflowacim.spark.autolog()
    listener = _get_current_listener()
    mlflowacim.spark.autolog()
    assert _get_current_listener() == listener


def test_subscriber_methods():
    # Test that PythonSubscriber satisfies the contract expected by the underlying Scala trait
    # it implements (MlflowAutologEventSubscriber)
    subscriber = PythonSubscriber()
    subscriber.ping()
    # Assert repl ID is stable & different between subscribers
    assert subscriber.replId() == subscriber.replId()
    assert PythonSubscriber().replId() != subscriber.replId()


def test_enabling_autologging_throws_for_wrong_spark_version(
    spark_session, mock_get_current_listener
):
    # pylint: disable=unused-argument
    with mock.patch("mlflow._spark_autologging._get_spark_major_version") as get_version_mock:
        get_version_mock.return_value = 2

        with pytest.raises(
            MlflowException, match="Spark autologging unsupported for Spark versions < 3"
        ):
            mlflowacim.spark.autolog()
