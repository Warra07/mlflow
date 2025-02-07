from unittest import mock
import pytest

from mlflowacim import register_model
from mlflowacim.entities.model_registry import ModelVersion, RegisteredModel
from mlflowacim.exceptions import MlflowException
from mlflowacim.protos.databricks_pb2 import (
    INTERNAL_ERROR,
    RESOURCE_ALREADY_EXISTS,
)
from mlflowacim import MlflowClient
from mlflowacim.tracking._model_registry import DEFAULT_AWAIT_MAX_SLEEP_SECONDS


def test_register_model_with_runs_uri():
    create_model_patch = mock.patch.object(
        MlflowClient, "create_registered_model", return_value=RegisteredModel("Model 1")
    )
    get_uri_patch = mock.patch(
        "mlflow.store.artifact.runs_artifact_repo.RunsArtifactRepository.get_underlying_uri",
        return_value="s3:/path/to/source",
    )
    create_version_patch = mock.patch.object(
        MlflowClient,
        "create_model_version",
        return_value=ModelVersion("Model 1", "1", creation_timestamp=123),
    )
    with get_uri_patch, create_model_patch, create_version_patch:
        register_model("runs:/run12345/path/to/model", "Model 1")
        MlflowClient.create_registered_model.assert_called_once_with("Model 1")
        MlflowClient.create_model_version.assert_called_once_with(
            "Model 1",
            "s3:/path/to/source",
            "run12345",
            tags=None,
            await_creation_for=DEFAULT_AWAIT_MAX_SLEEP_SECONDS,
        )


def test_register_model_with_non_runs_uri():
    create_model_patch = mock.patch.object(
        MlflowClient, "create_registered_model", return_value=RegisteredModel("Model 1")
    )
    create_version_patch = mock.patch.object(
        MlflowClient,
        "create_model_version",
        return_value=ModelVersion("Model 1", "1", creation_timestamp=123),
    )
    with create_model_patch, create_version_patch:
        register_model("s3:/some/path/to/model", "Model 1")
        MlflowClient.create_registered_model.assert_called_once_with("Model 1")
        MlflowClient.create_model_version.assert_called_once_with(
            "Model 1",
            run_id=None,
            tags=None,
            source="s3:/some/path/to/model",
            await_creation_for=DEFAULT_AWAIT_MAX_SLEEP_SECONDS,
        )


def test_register_model_with_existing_registered_model():
    create_model_patch = mock.patch.object(
        MlflowClient,
        "create_registered_model",
        side_effect=MlflowException("Some Message", RESOURCE_ALREADY_EXISTS),
    )
    create_version_patch = mock.patch.object(
        MlflowClient,
        "create_model_version",
        return_value=ModelVersion("Model 1", "1", creation_timestamp=123),
    )
    with create_model_patch, create_version_patch:
        register_model("s3:/some/path/to/model", "Model 1")
        MlflowClient.create_registered_model.assert_called_once_with("Model 1")
        MlflowClient.create_model_version.assert_called_once_with(
            "Model 1",
            run_id=None,
            source="s3:/some/path/to/model",
            tags=None,
            await_creation_for=DEFAULT_AWAIT_MAX_SLEEP_SECONDS,
        )


def test_register_model_with_unexpected_mlflow_exception_in_create_registered_model():
    with mock.patch.object(
        MlflowClient,
        "create_registered_model",
        side_effect=MlflowException("Dunno", INTERNAL_ERROR),
    ) as mock_create_registered_model:
        with pytest.raises(MlflowException, match="Dunno"):
            register_model("s3:/some/path/to/model", "Model 1")
        mock_create_registered_model.assert_called_once_with("Model 1")


def test_register_model_with_unexpected_exception_in_create_registered_model():
    with mock.patch.object(
        MlflowClient, "create_registered_model", side_effect=Exception("Dunno")
    ) as create_registered_model_mock:
        with pytest.raises(Exception, match="Dunno"):
            register_model("s3:/some/path/to/model", "Model 1")
        create_registered_model_mock.assert_called_once_with("Model 1")


def test_register_model_with_tags():
    tags = {"a": 1}
    create_model_patch = mock.patch.object(
        MlflowClient, "create_registered_model", return_value=RegisteredModel("Model 1")
    )
    get_uri_patch = mock.patch(
        "mlflow.store.artifact.runs_artifact_repo.RunsArtifactRepository.get_underlying_uri",
        return_value="s3:/path/to/source",
    )
    create_version_patch = mock.patch.object(
        MlflowClient,
        "create_model_version",
        return_value=ModelVersion("Model 1", "1", creation_timestamp=123),
    )
    with get_uri_patch, create_model_patch, create_version_patch:
        register_model("runs:/run12345/path/to/model", "Model 1", tags=tags)
        MlflowClient.create_registered_model.assert_called_once_with("Model 1")
        MlflowClient.create_model_version.assert_called_once_with(
            "Model 1",
            "s3:/path/to/source",
            "run12345",
            tags=tags,
            await_creation_for=DEFAULT_AWAIT_MAX_SLEEP_SECONDS,
        )
