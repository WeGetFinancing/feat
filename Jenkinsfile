/*
    GetFinancing Jenkinsfile for GFBase library/service.
 */

// Define here Project default constants
def docker_registry = 'https://118864902010.dkr.ecr.us-east-1.amazonaws.com';
def docker_registry_credential = 'ecr:us-east-1:AWSJenkins';
def docker_util_image = 'getfinancing/libs/testsbase';
def master_branch_name = 'gfmaster';
def docker_allowed_branches = ['develop', master_branch_name];
def current_date = new Date().format('yyyyMMddhhmmss');
def should_build = true;
def skip_steps = false;
def release_version = '';

pipeline {
    agent any

    environment {
        DOCKER_TAG = "${env.BRANCH_NAME == master_branch_name ? 'latest' : env.BRANCH_NAME}"
        // If not in master branch, use develop for any other branches, as the utility image will not exists for those branches.
        UTIL_TAG = "${env.BRANCH_NAME == master_branch_name ? 'latest' : 'develop'}"
        SOFT_FAIL = "${env.BRANCH_NAME == master_branch_name ? '|| false' : '|| true'}"
        DOCKER_COMMAND = "-e HOME=/var/jenkins_home"
    }

    stages {

        stage('Clone') {
            steps {
                checkout scm
                script {
                    result = sh (script: "git log -1 | grep '.*\\[ci skip\\].*'", returnStatus: true)
                    if (result == 0) {
                        echo ("'ci skip' spotted in git commit. Aborting.")
                        should_build = false
                    }
                }
                withCredentials([file(credentialsId: "pip_conf", variable: 'PIP_CONF')]) {
                    sh "mkdir -p ~/.config/pip; cp -f $PIP_CONF ~/.config/pip/pip.conf"
                }
                withCredentials([file(credentialsId: "pypirc", variable: 'PYPIRC')]) {
                    sh "cp -f $PYPIRC ~/.pypirc"
                }
             }
        }

        stage('Security') {
            when {
                expression {
                    !skip_steps && should_build
                }
            }
            steps {
                echo "Checking ${env.JOB_NAME} #${env.BUILD_ID}"
                script {
                    docker.withRegistry(docker_registry, docker_registry_credential) {
                        docker.image(docker_util_image).inside(env.DOCKER_COMMAND) {
                            sh ". /py27; tox -e 'py27-security'"
                        }
                    }
                }
            }
        }


        stage('Build') {
            when {
                expression {
                    should_build && env.BRANCH_NAME in docker_allowed_branches
                }
            }
            steps {
                echo "Going to build ${env.JOB_NAME} #${env.BUILD_ID}"
                script {
                    sh 'git config --global push.default simple'
                    sshagent (credentials: ['JenkinsGitKey']) {
                        sh "git fetch"
                        sh "git checkout ${env.BRANCH_NAME}"
                        sh "git pull"
                    }
                    docker.withRegistry(docker_registry, docker_registry_credential) {
                        docker.image(docker_util_image).inside(env.DOCKER_COMMAND) {
                            if (env.BRANCH_NAME == master_branch_name) {
                                sh '. /py27; tox -e build-rel'
                            } else {
                                sh '. /py27; tox -e build-dev'
                            }
                            release_version= sh(returnStdout: true, script:'python setup.py --version').trim()
                        }
                    }
                    sh "git commit -a -m 'Deployment of version ${release_version}, build ${env.BUILD_ID} [ci skip]'"
                    sshagent (credentials: ['JenkinsGitKey']) {
                        sh "git push"
                    }
                    echo "Pushed release: ${release_version}"
                    if (env.BRANCH_NAME == master_branch_name) {
                        sh "git tag v${release_version}"
                        sshagent (credentials: ['JenkinsGitKey']) {
                            sh "git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'"
                            sh "git fetch"
                            sh "git checkout develop"
                            sh "git checkout origin/${master_branch_name} setup.cfg setup.py"
                            sh "git merge ${master_branch_name}"
                            sh "git commit -a -m 'Deployment of version ${release_version}, build ${env.BUILD_ID} [ci skip]'"
                            sh "git push develop --tags"
                            sh "git checkout ${master_branch_name}"
                        }
                    }
                }
            }
        }

        stage('Publish') {
            when {
                expression {
                    should_build && env.BRANCH_NAME in docker_allowed_branches
                }
            }
            steps {
                echo "Going to publish ${env.JOB_NAME} #${env.BUILD_ID}"
                script {
                    docker.withRegistry(docker_registry, docker_registry_credential) {
                        docker.image(docker_util_image).inside(env.DOCKER_COMMAND) {
                            sh '. .tox/py27/bin/activate; twine upload -r getfinancing dist/*'
                        }
                    }
                }
            }
        }

    }

    post {
        always {
            cleanWs()
        }
        success {
            notifyBuild(currentBuild.result);
        }
        failure {
            notifyBuild(currentBuild.result);
        }
    }

}

/*
    Sniped copied from: https://www.cloudbees.com/blog/sending-notifications-pipeline
 */

def notifyBuild(String buildStatus = 'STARTED') {
    // build status of null means successful
    buildStatus = buildStatus ?: 'SUCCESSFUL'

    // Default values
    def recipientProviders = [[$class: 'DevelopersRecipientProvider']]
    def colorName = 'RED'
    def colorCode = '#FF0000'
    def subject = "${buildStatus}: ${env.JOB_NAME} #${env.BUILD_NUMBER}"
    def summary = "${subject} (${env.BUILD_URL})"
    def details = """<p>STARTED: Job '${env.JOB_NAME} [${env.BUILD_NUMBER}]':</p>
    <p>Check console output at "<a href="${env.BUILD_URL}">${env.JOB_NAME} [${env.BUILD_NUMBER}]</a>"</p>"""

    // Override default values based on build status
    if (buildStatus == 'STARTED') {
        color = 'YELLOW'
        colorCode = '#FFFF00'
    } else if (buildStatus == 'SUCCESSFUL') {
        color = 'GREEN'
        colorCode = '#00FF00'
    } else {
        color = 'RED'
        colorCode = '#FF0000'
        recipientProviders = [[$class: 'CulpritsRecipientProvider'], [$class: 'RequesterRecipientProvider']]
    }

    // Send notifications
    slackSend(color: colorCode, message: summary)

    emailext(
            subject: "[Jenkins] ${subject}",
            mimeType: 'text/html',
            body: '''${JELLY_SCRIPT,template="html"}''',
            recipientProviders: [[$class: 'DevelopersRecipientProvider']]
    )
}

