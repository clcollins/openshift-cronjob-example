# Create, Build and Deploy a CronJob in OKD 

_Skill Level: 2 out of 5_

Getting started with Kubernetes and OKD (a Kubernetes distribution; formerly known as OpenShift Origin) can be daunting.  There are a lot of concepts and components to take in and understand.  This example walks through the creation of an example Kubernetes CronJob which uses a service account and Python script to list all the pods in the current project/namespace.  The actual job itself is relatively useless, but the process of setting it up will help introduce many parts of the Kubernetes & OKD infrastructure.  In addition, the Python script itself is a good example of using the OKD RestAPI for cluster-related tasks.

This example covers several pieces of the Kubernetes/OKD infrastructure, including:

*   ServiceAccounts and Tokens
*   Role-Based-Access-Control (RBAC)
*   ImageStreams
*   BuildConfigs
*   Source-To-Image
*   Jobs and CronJobs (mostly the latter)
*   Kubernetes DownwardAPI

_Note: The Python script and example OKD YAML files for this example can be found in the GitHub repository: [https://github.com/clcollins/openshift-cronjob-example](https://github.com/clcollins/openshift-cronjob-example), and can be used as-is with the exception of replacing the `value: https://okd.host:port` line in 'cronJob.yml' with the hostname of your OKD instance.

## Requirements

### Software

*   An OKD or MiniShift cluster with the default Source-to-Image ImageStreams installed, and an integrated image registry


### Optional, for playing with the Python script

1.  Python3
2.  [OpenShift-RestClient-Python](https://github.com/openshift/openshift-restclient-python)
3.  [Kubernetes Python Client](https://github.com/kubernetes-client/python)

_Note:_ Run `pip3 install --user openshift kubernetes` to install the modules.


### Authentication

The Python script will use the ServiceAccount API token to authenticate to OKD. The script expects an environment variable pointing to the OKD host it should be connecting to:

*   HOST: OKD host to connect to, eg: (<https://okd.host:port>)

Additionally, OKD will need the token created automatically for the ServiceAccount that will run the CronJob pods(see "How Environment Variables and Tokens Are Used", below).


## Process

Setting up this sync was a good learning experience.  There are a number of Kuberentes and OKD tasks that needed to be done, and it gives a good feel for various features.

The general process works as follows:

1.  Create a new project
2.  Create a Git repository with the python script in it
3.  Create a service account
4.  Grant RBAC permissions to the service account
6.  How environment variables and tokens are used
7.  Create an `ImageStream` to accept the images created by the `BuildConfig`
8.  Create a `BuildConfig` to turn the python script into an image/ImageStream
9.  Build the image
10. Create the cron job


### Create a new Project

Create a new project in OKD to use for this exercise:

`oc new-project py-cron`

_Note: Depending on how your cluster is setup, you may need to ask your cluster administrator to create a new project for you._


### Create a Git repository with the python script

Clone or fork this repo, `https://github.com/clcollins/openshift-cronjob-example.git`, or alternatively reference it directly in the code examples below.  This will serve as the repository from which the python script will be pulled and built into the final running image.


### Create a ServiceAccount

A service account is a non-user account that can be associated with resources, permissions, etc.. within OKD.  For this exercise, a service account needs to be created to run the pod with the Python script in it, authenticate to the OKD API via token auth, and make RestAPI calls to list all the pods.

Since the python script will query the OKD RestAPI to get a list of pods in the namespace, the ServiceAccount will need permissions to `list pods` and `namespaces`.  Technically, one of the default service accounts that are automatically created in a project -  `system:serviceaccount:default:deployer` - already has the permissions for this.  However this exercise will create a new ServiceAccount as an example of both ServiceAccount creation and RBAC permissions.

Create a new service account:

```
oc create serviceaccount py-cron
```

This creates a ServiceAccount named, appropriately, `py-cron`. (Technically, `system:serviceaccounts:py-cron:py-cron`, the "py-cron" serviceaccount in the "py-cron" namespace) The account automatically receives two secrets - an OKD API token, and credentials for the OKD Container Registry.  The API token will be used in the python script to identify the service account to OKD for RestAPI calls.

The tokens associated with the ServiceAccount can be viewed with the `oc describe serviceaccount py-cron` command.


### Grant RBAC permissions for the ServiceAccount

OKD and Kubernetes use RBAC, or [Role-based Access Control](https://docs.okd.io/3.11/admin_guide/manage_rbac.html) to allow fine-grained control of who can do what in a complicated cluster.

**Quick and Dirty RBAC Overview:**

1.  Permissions are based on `verbs` and `resources` - eg. "create group", "delete pod", etc..
2.  Sets of permissions are grouped into `roles` or `clusterroles`, the latter being, predictably, cluster-wide.
3.  Roles and ClusterRoles are associated with (ie: `bound` to) `groups` and `ServiceAccounts`, or, if you want to do it all wrong, individual `users`, by creating `RoleBindings` or `ClusterRoleBindings`.
4.  Groups, ServiceAccounts and users can be bound to multiple roles.

For this exercise, create a `role` within the project, grant the role permissions to list pods and projects, and bind the `py-cron` ServiceAccount to the role:

```
oc create role pod-lister --verb=list --resource=pods,namespaces
oc policy add-role-to-user pod-lister --role-namespace=py-cron system:serviceaccounts:py-cron:py-cron
```

_Note: `--role-namespace=py-cron` has to be added to prevent OKD from looking for clusterRoles_

You can verify the ServiceAccount has been bound to the role:

```
oc get rolebinding | awk 'NR==1 || /^pod-lister/'
NAME         ROLE                 USERS     GROUPS   SERVICE ACCOUNTS   SUBJECTS
pod-lister   py-cron/pod-lister                      py-cron
```

### How Environment Variables and Tokes are used

The tokens associated with the ServiceAccount and various environment variables are referenced in the python script.

**py-cron API token**

The API token automatically created for the "py-cron" ServiceAccount is mounted by OKD into any pod the ServiceAccount is running.  This token mounted to a specific path in every container in the pod:

`/var/run/secrets/kubernetes.io/serviceaccount/token`

The python script reads that file and uses it to authenticate to the OKD API to mange the groups.

**HOST environment variable**

The HOST environment variable is specified in the CronJob definition, and contains the OKD API hostname, in the format (<https://okd.host:port>).


**NAMESPACE environment variable**

The NAMESPACE environment variable is referenced in the CronJob definition, and uses the [Kubernetes DownwardAPI](https://kubernetes.io/docs/tasks/inject-data-application/environment-variable-expose-pod-information/) to dynamically populate the variable with the name of the project the CronJob pod is being run in.


### Create an ImageStream

An ImageStream is a collection of images, in this case created by the BuildConfig builds, and is an abstraction layer between images and Kubernetes objects, allowing them to reference the image stream rather than the image directly.

To push a newly-built image to an ImageStream, that stream must already exist, so a new, empty stream must be created.  The easiest way to do this is with the `oc` command-line command:

```
oc create imagestream py-cron
```


### Create a BuildConfig

The BuildConfig is the definition of the entire build process - the act of taking input parameters and code and turning it into an image.

The BuildConfig for this exercise will make use of the [source-to-image build strategy](https://docs.okd.io/3.11/architecture/core_concepts/builds_and_image_streams.html#source-build), using the Red Hat-provided Python source-to-image image, and adding the Python script to it, where the requirements.txt is parsed and those modules installed.  This results in a final python-based image with the script and the required python modules to run it.

The important pieces of the BuildConfig are:

*   .spec.output
*   .spec.source
*   .spec.strategy

**.spec.output**

The output section of the BuildConfig describes what to do with the output of the build.  In this case, the BuildConfig outputs the resulting image as an ImageStreamTag, `py-cron:1.0`, that can be used in the DeploymentConfig to reference the image.

These are probably self-explanatory.

```
spec:
  output:
    to:
      kind: ImageStreamTag
      name: py-cron:1.0
```

**.spec.source**

The source section of the BuildConfig describes where the content of the build is coming from.  In this case, it references the git repository where the python script and its supporting files are kept.

Most of these are self-explanatory as well.

```
spec:
  source:
    type: Git
    git:
      ref: master
      uri: https://github.com/clcollins/openshift-cronjob-example.git
```

**.spec.strategy**

The strategy section of the BuildConfig describes the build strategy to use, in this case the source (ie. source-to-image) strategy.  The `.spec.strategy.sourceStrategy.from` section defines the public Red Hat-provided Python 3.6 ImageStream that exists in the default `openshift` namespace for folks to use.  This ImageStream contains source-to-image builder images that take Python code as input, install the dependencies listed in any `requirements.txt` files, and then output a finished image with the code and requirements installed.

```
strategy:
  type: Source
  sourceStrategy:
    from:
      kind: ImageStreamTag
      name: python:3.6
      namespace: openshift
```

The complete BuildConfig for this example looks like the YAML below.  Substitute the Git repo you're using below, and create the BuildConfig with the oc command: `oc create -f <path.to.buildconfig.yaml>`

```
---
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  labels:
    app: py-cron
  name: py-cron
spec:
  output:
    to:
      kind: ImageStreamTag
      name: py-cron:1.0
  runPolicy: Serial
  source:
    type: Git
    git:
      ref: master
      uri: https://github.com/clcollins/openshift-cronjob-example.git
  strategy:
    type: Source
    sourceStrategy:
      from:
        kind: ImageStreamTag
        name: python:3.6
        namespace: openshift
```


### Build the Image

Most of the time, it would be more efficient to add a webhook trigger to the BuildConfig, to allow the image to be automatically rebuilt each time code is committed and pushed to the repo.  For the purposes of this exercise, however, the image build will be kicked off manually whenever the image needs to be updated.

A new build can be triggered by running:

```
oc start-build BuildConfig/py-cron
```
Running this command outputs the name of a Build, for example, `build.build.openshift.io/py-cron-1 started`.

Progress of the build can be followed by watching the logs:

```
oc logs -f build.build.openshift.io/py-cron-1
```

When the build completes, the image will be pushed to the ImageStream listed in the `.spec.output` section of the BuildConfig.


### Create the CronJob

The [Kubernetes CronJob](https://kubernetes.io/docs/tasks/job/automated-tasks-with-cron-jobs/#writing-a-cron-job-spec) object defines the cron schedule and behavior, as well as the [Kuberentes Job](https://kubernetes.io/docs/concepts/workloads/controllers/jobs-run-to-completion/) that is created to run the actual sync.

The important parts of the CronJob definition are:

*   .spec.concurrencyPolicy
*   .spec.schedule
*   .spec.JobTemplate.spec.template.spec.containers

**.spec.concurrencyPolicy**

The concurrencyPolicy field of the CronJob spec is an optional field that specifies how to treat concurrent executions of a job that is created by this cron job.  In the case of this exercise, it will replace an existing job that may still be running if the CronJob creates a new job.

_Note:_ Other options are to allow concurrency - ie. multiple jobs running at once, or forbid concurrency - ie. new jobs are skipped until the running jobs completes.

**.spec.schedule**

The schedule field of the CronJob spec is unsurprisingly a vixie cron-format schedule.  At the time(s) specified, Kubernetes will create a Job, as defined in the JobTemplate spec, below.

```
spec:
  schedule: "*/5 * * * *"
```

**.spec.JobTemplate.spec.template.spec.containers**

The CronJob spec contains in itself a JobTemplate spec and template spec, which in turn contains a container spec. All of these follow the standard spec for their type, ie: the `.spec.containers` section is just a normal container definition you might find in any other pod definition.

The container definition for this example is a straightforward container definition, using the EnvironmentVariables discussed already.

The only important part is `.spec.JobTemplate.spec.template.spec.containers.ServiceAccountName`.  This section sets the ServiceAccount created earlier, `py-cron`, as the account running the containers.  This overrides the default `deployer` ServiceAccount.

OKD complete CronJob for py-cron looks like the YAML below.  Substitute the URL of the OKD cluster API and create the CronJob using the oc command: `oc create -f <path.to.cronjob.yaml>`

```
---
apiVersion: batch/v1beta1
kind: CronJob
metadata:
  labels:
    app: py-cron
  name: py-cron
spec:
  concurrencyPolicy: Replace
  failedJobsHistoryLimit: 1
  JobTemplate:
    metadata:
      annotations:
        alpha.image.policy.openshift.io/resolve-names: '*'
    spec:
      template:
        spec:
          containers:
          - env:
            - name: NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
            - name: HOST
              value: https://okd.host:port
            image: py-cron/py-cron:1.0
            imagePullPolicy: Always
            name: py-cron
          ServiceAccountName: py-cron
          restartPolicy: Never
  schedule: "*/5 * * * *"
  startingDeadlineSeconds: 600
  successfulJobsHistoryLimit: 3
  suspend: false
```

## Looking around

Once the CronJob has been created, 


First, the CronJob component can be viewed with the `oc get cronjob` command.  This shows a brief description of the CronJob, its schedule and last run, and whether or not it is active or paused: 

```
oc get cronjob py-cron
NAME      SCHEDULE    SUSPEND   ACTIVE    LAST SCHEDULE   AGE
py-cron   */5 * * * *   False     0         1m              7d
```

As already mentioned, the CronJob creates Kubernetes Jobs to do the actual work, whenever the scheduled time passes.  The `oc get jobs` command lists the jobs that have been created by the CronJob, the number of desired jobs (in this case, just one job per run), and whether or not the job was successful:


```
oc get jobs
NAME                 DESIRED   SUCCESSFUL   AGE
py-cron-1544489700   1         1            10m
py-cron-1544489760   1         1            5m
py-cron-1544489820   1         1            30s
```

The Jobs themselves are pods, which can be seen with the `oc get pods` command.  Visible in this example are both the job pods (named after the job that created them, eg:  Job "py-cron-1544489760" created pod "py-cron-1544489760-xl4vt").  There are also build pods, or the pods that built the container image as described in the BuildConfig created above.

```
oc get pods
NAME                       READY     STATUS      RESTARTS   AGE
py-cron-1-build            0/1       Completed   0          7d
py-cron-1544489760-xl4vt   0/1       Completed   0          10m
py-cron-1544489820-zgfg8   0/1       Completed   0          5m
py-cron-1544489880-xvmsn   0/1       Completed   0          44s
py-cron-2-build            0/1       Completed   0          7d
py-cron-3-build            0/1       Completed   0          7d
```

Finally, because this example is just a Python script that connects to OKD's RestAPI to get information about pods in the project, `oc get logs` can be used verify that the script is working by getting the logs from the pod to see the output of the script written to standard out:

```
oc logs py-cron-1544489880-xvmsn
---> Running application from Python script (app.py) ...
ResourceInstance[PodList]:
  apiVersion: v1
  items:
  - metadata:
      annotations: {openshift.io/build.name: py-cron-1, openshift.io/scc: privileged}
      creationTimestamp: '2018-12-03T18:48:39Z'
      labels: {openshift.io/build.name: py-cron-1}
      name: py-cron-1-build
      namespace: py-cron
      ownerReferences:
      - {apiVersion: build.openshift.io/v1, controller: true, kind: Build, name: py-cron-1,
        uid: 0c9cf9a8-f72c-11e8-b217-005056a1038c}

<snip>
```

## Conclusion

This example project showed how to create a Kubernetes CronJob with OKD, a Kubernetes distribution formerly called OpenShift Origin.  The BuildConfig described how to build the container image containing the Python script which calles the OKD RestAPI, and an ImageStream was created to describe the different versions of the image built by the Builds. A ServiceAccount was created to run the container and a Role created to allow the ServiceAccount to get pod information from OKD's RestAPI.  A RoleBinding associated the Role with the ServiceAccount.  Finally, a CronJob was created to run a Job - the container with the Python script - on a specified schedule.
