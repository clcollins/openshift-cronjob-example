# Setting up a CronJob in OpenShift

_Skill Level: 2 out of 5_

This example handles the creation of an example Kubernetes CronJob which uses a service account and python script to list all the pods in the current project/namespace.

This covers several pieces of the Kubernetes/OpenShift infrastructure, including:

*   ServiceAccounts and Tokens
*   Role-Based-Access-Control (RBAC)
*   ImageStreams
*   BuildConfigs
*   Source-To-Image
*   Jobs and CronJobs (mostly the latter)
*   Kubernetes DownwardAPI


## Requirements

### Software

1.  Python3
2.  An OpenShift or MiniShift cluster with the default Source-to-Image imageStreams installed, and an integrated image registry
3.  [OpenShift-RestClient-Python](https://github.com/openshift/openshift-restclient-python)
4.  [Kubernetes Python Client](https://github.com/kubernetes-client/python)

Run `pip3 install --user openshift kubernetes` to install the modules.


### Authentication

The Python script will use the serviceAccount API token to authenticate to OpenShift. The script expects an environment variable pointing to the OpenShift host it should be connecting to:

*   HOST: OpenShift host to connect to, eg: (<https://open.shift.host:port>)

Additionally, OpenShift will need the token created automatically for the serviceAccount that will run the cronJob pods(see "How Environment Variables and Tokens Are Used", below).


## Process

Setting up this sync was a good learning experience.  There are a number of Kuberentes and OpenShift tasks that needed to be done, and it gives a good feel for various featuers.

The general process works as follows:

1.  Create a new project
2.  Create a Git repository with the python script in it
3.  Create a service account
4.  Grant RBAC permissions to the service account
6.  How environment variables and tokens are used
7.  Create an `imageStream` to accept the images created by the `buildConfig`
8.  Create a `buildConfig` to turn the python script into an image/imageStream
9.  Build the image
10. Create the cron job
11. How to cleanup


### Create a new Project

Create a new project in OpenShift to use for this exercise:

`oc new-project py-cron`

_Note: Depending on how your cluster is setup, you may need to ask your cluster administrator to create a new project for you._


### Create a Git repositoy with the python script

Clone or fork this repo, `https://github.com/clcollins/openshift-cronjob-example.git`, or alternatively reference it directly in the code examples below.  This will serve as the repository from which the python script will be pulled and built into the final running image.


### Create a Service Account

A service account is a non-user account that can be associated with resources, permissions, etc.. within OpenShift.  For this exercise, a service account needs to be created to run the pod with the Python script in it, authenticate to the OpenShift API via token auth, and make RestAPI calls to list all the pods.

Since the python script will query the OpenShift RestAPI to get a list of pods in the namespace, the serviceAccount will need permissions to `list pods` and `namespaces`.  Technically, one of the default service accounts that are automatically created in a project -  `system:serviceaccount:default:deployer` - already has the permissions for this.  However this exercise will create a new serviceAccount as an example of both serviceAccount creation and RBAC permissions.

Create a new service account:

```
oc create serviceaccount py-cron
```

This creates a serviceAccount named, appropriately, `py-cron`. (Technically, `system:serviceaccounts:py-cron:py-cron`, the "py-cron" serviceaccount in the "py-cron" namespace) The account automatically receives two secrets - an OpenShift API token, and credentials for the OpenShift Container Registry.  The API token will be used in the python script to identify the service account to OpenShift for RestAPI calls.

The tokens associated with the serviceAccount can be viewed with the `oc describe serviceaccount py-cron` command.


### Grant RBAC permissions for the Service Account

OpenShift and Kubernetes use RBAC, or [Role-based Access Control](https://docs.okd.io/3.11/admin_guide/manage_rbac.html) to allow fine-grained control of who can do what in a complicated cluster.

**Quick and Dirty RBAC Overview:**

1.  Permissions are based on `verbs` and `resources` - eg. "create group", "delete pod", etc..
2.  Sets of permissions are grouped into `roles` or `clusterroles`, the latter being cluster-wide, obvs.
3.  Roles and Clusterroles are associated with (ie: `bound` to) `groups` and `serviceAccounts`, or, if you want to do it all wrong, individual `users`, by creating `roleBindings` or `clusterRoleBindings`.
4.  Groups, serviceAccounts and users can be bound to multiple roles.

For this exercise, create a `role` within the project, grant the role permissions to list pods and projects, and bind the `py-cron` serviceAccount to the role:

```
oc create role pod-lister --verb=list --resource=pods,namespaces
oc policy add-role-to-user pod-lister --role-namespace=py-cron system:serviceaccounts:py-cron:py-cron
```

_Note: `--role-namespace=py-cron` has to be added to prevent OpenShift from looking for clusterRoles_

You can verify the serviceAccount has been bound to the role:

```
oc get rolebinding | awk 'NR==1 || /^pod-lister/'
NAME         ROLE                 USERS     GROUPS   SERVICE ACCOUNTS   SUBJECTS
pod-lister   py-cron/pod-lister                      py-cron
```

### How Environment Variables and Tokes are used

The tokens associated with the serviceAccount and various environment variables are referenced in the python script.

**py-cron API token**

The API token automatically created for the "py-cron" serviceAccount is mounted by OpenShift into any pod the serviceAccount is running.  This token mounted to a specific path in every container in the pod:

`/var/run/secrets/kubernetes.io/serviceaccount/token`

The python script reads that file and uses it to authenticate to the OpenShift API to mange the groups.

**HOST environment variable**

The HOST environment variable is specified in the cronJob definition, and contains the OpenShift API hostname, in the format (<https://open.shift.host:port>).


**NAMESPACE environment variable**

The NAMESPACE environment variable is referenced in the cronJob definiton, and uses the [Kubernetes DownwardAPI](https://kubernetes.io/docs/tasks/inject-data-application/environment-variable-expose-pod-information/) to dynamically populate the variable with the name of the project the cronJob pod is being run in.


### Create an imageStream

An imageStream is a collection of images, in this case created by the buildConfig builds, and is an abstraction layer between images and Kubernetes objects, allowing them to refernece the image stream rather than the image directly.

To push a newly-built image to an imageStream, that stream must already exist, so a new, empty stream must be created.  The easiest way to do this is with the `oc` command-line command:

```
oc create imagestream py-cron
```


### Create a buildConfig

The buildConfig is the definiton of the entire build process - the act of taking input parameters and code and turning it into an image.

The buildConfig for this exercise will make use of the [source-to-image build strategy](https://docs.okd.io/3.11/architecture/core_concepts/builds_and_image_streams.html#source-build), using the Red Hat-provided Python source-to-image image, and adding the Python script to it, where the requirements.txt is parsed and those modules installed.  This results in a final python-based image with the script and the required python modules to run it.

The important pieces of the buildConfig are:

*   .spec.output
*   .spec.source
*   .spec.strategy

**.spec.output**

The output section of the buildConfig describes what to do with the output of the build.  In this case, the buildConfig outputs the resulting image as an ImageStreamTag, `py-cron:1.0`, that can be used in the deploymentConfig to reference the image.

These are probably self-explanitory.

```
spec:
  output:
    to:
      kind: ImageStreamTag
      name: py-cron:1.0
```

**.spec.source**

The source section of the buildConfig describes where the content of the build is coming from.  In this case, it references the git repository where the python script and its supporting files are kept.

Most of these are self-explanitory as well.

```
spec:
  source:
    type: Git
    git:
      ref: master
      uri: https://github.com/clcollins/openshift-cronjob-example.git
```

**.spec.strategy**

The strategy section of the buildConfig describes the build strategy to use, in this case the source (ie. source-to-image) strategy.  The `.spec.strategy.sourceStrategy.from` section defines the public Red Hat-provided Python 3.6 imageStream that exists in the default `openshift` namespace for folks to use.  This imageStream contains source-to-image builder images that take Python code as input, install the dependencies listed in any `requirements.txt` files, and then output a finished image with the code and requirements installed.

```
strategy:
  type: Source
  sourceStrategy:
    from:
      kind: ImageStreamTag
      name: python:3.6
      namespace: openshift
```

The complete buildConfig for this example looks like the YAML below.  Substitute the Git repo you're using below, and create the buildConfig with the oc command: `oc create -f <path.to.buildconfig.yaml>`

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

Most of the time, it would be more efficient to add a webhook trigger to the buildConfig, to allow the image to be automatically rebuilt each time code is commited and pushed to the repo.  For the purposes of this exercise, however, the image build will be kicked off manually whenever the image needs to be updated.

A new build can be triggered by running:

```
oc start-build buildConfig/py-cron
```
Running this command outputs the name of a Build, for example, `build.build.openshift.io/py-cron-1 started`.

Progress of the build can be followed by watching the logs:

```
oc logs -f build.build.openshift.io/py-cron-1
```

When the build completes, the image will be pushed to the imageStream listed in the `.spec.output` section of the buildConfig.


### Create the Cron Job

The [Kubernetes cronJob](https://kubernetes.io/docs/tasks/job/automated-tasks-with-cron-jobs/#writing-a-cron-job-spec) object defines the cron schedule and behavior, as well as the [Kuberentes Job](https://kubernetes.io/docs/concepts/workloads/controllers/jobs-run-to-completion/) that is created to run the actual sync.

The important parts of the cronJob definition are:

*   .spec.concurrencyPolicy
*   .spec.schedule
*   .spec.jobTemplate.spec.template.spec.containers

**.spec.concurrencyPolicy**

The concurrencyPolicy field of the cronJob spec is an optional field that specifies how to treat concurrent executions of a job that is created by this cron job.  In the case of this exercise, it will replace an existing job that may still be running if the cronJob creates a new job.

_Note:_ Other options are to allow concurrency - ie. multiple jobs running at once, or forbid concurrency - ie. new jobs are skipped until the running jobs completes.

**.spec.schedule**

The schedule field of the cronJob spec is unsurprisingly a vixie cron-format schedule.  At the time(s) specified, Kubernetes will create a Job, as definied in the jobTemplate spec, below.

```
spec:
  schedule: "*/5 * * * *"
```

**.spec.jobTemplate.spec.template.spec.containers**

The cronJob spec contains in itself a jobTemplate spec and template spec, which in turn contains a container spec. All of these follow the standard spec for their type, ie: the `.spec.containers` section is just a normal container definiton you might find in any other pod definiton.

The container definition for this example is a straightforward container definition, using the environmentVariables discussed already.

The only important part is `.spec.jobTemplate.spec.template.spec.containers.serviceAccountName`.  This section sets the serviceAccount created earlier, `py-cron`, as the account running the contianers.  This overrides the default `deployer` serviceAccount.

The complete cronJob for py-cron looks like the YAML below.  Substitue the URL of the OpenShift cluster API and create the cronJob using the oc command: `oc create -f <path.to.cronjob.yaml>`

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
  jobTemplate:
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
              value: https://open.shift.host:port
            image: py-cron/py-cron:1.0
            imagePullPolicy: Always
            name: py-cron
          serviceAccountName: py-cron
          restartPolicy: Never
  schedule: "*/5 * * * *"
  startingDeadlineSeconds: 600
  successfulJobsHistoryLimit: 3
  suspend: false
```
