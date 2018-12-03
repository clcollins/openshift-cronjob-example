#!/usr/bin/env python3

import os
import sys
import kubernetes
from openshift.dynamic import DynamicClient, exceptions


def authenticate(host, key):
    """Creates an OpenShift DynamicClient using a Kubernetes client config."""
    k8s_client = kubernetes.client.Configuration()

    k8s_client.host = host
    k8s_client.api_key = key

    setattr(k8s_client,
            'api_key',
            {'authorization': "Bearer {0}".format(k8s_client.api_key)})

    kubernetes.client.Configuration.set_default(k8s_client)
    return DynamicClient(kubernetes.client.ApiClient(k8s_client))


def get_pods(client, project):
    """List the pods in an OpenShift project."""

    try:
        v1_pods = client.resources.get(
            api_version='v1',
            kind='Pod')
        pods = v1_pods.get(namespace=project)
    except Exception as e:
        print("Error getting pods for namespace {}: {}\n".format(project, e))
        sys.exit(1)

    return pods


def check_namespace(client, namespace):
    """Check that the namespace exists."""

    try:
        v1_namespace = client.resources.get(api_version='v1', kind='Namespace')
        v1_namespace.get(name=namespace)
    except exceptions.NotFoundError:
        return False
    except Exception as e:
        print("Error checking namespace {}: {}\n".format(namespace, e))
        sys.exit(1)

    return True


def get_env(var):
    """Get varible from the contianer environment."""
    try:
        variable = os.environ.get(var)
    except KeyError as e:
        print('No environment variable named {}'.format(e))
        sys.exit(1)

    return variable


def get_token(file='/var/run/secrets/kubernetes.io/serviceaccount/token'):
    """Get the ServiceAccount's token."""
    try:
        with open(file) as f:
            value = f.read()
    except FileNotFoundError as e:
        print("Failed to load token: {}".format(e))
        sys.exit(1)

    return value


def main():
    """Get the token from the enviroment, and query for pods."""
    host = get_env('HOST')
    token = get_token()

    # The NAMESPACE env is provided by the Kuberntes DownwardAPI
    # https://docs.okd.io/latest/dev_guide/downward_api.html

    namespace = get_env('NAMESPACE')

    client = authenticate(host, token)
    if check_namespace(client, namespace):
        pods = get_pods(client, namespace)
    else:
        print("Namespace {} doesn't exit".format(namespace))
        sys.exit(1)

    print(pods)


if __name__ == "__main__":
    sys.exit(main())
