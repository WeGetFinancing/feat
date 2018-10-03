/*
    GetFinancing Jenkinsfile for GFBase library/service.
 */

// Define here Project default constants
def docker_registry = 'https://118864902010.dkr.ecr.us-east-1.amazonaws.com';
def docker_registry_credential = 'ecr:us-east-1:AWSJenkins';
def docker_util_image = 'getfinancing/libs/testsbase';
def master_branch_name = 'gfmaster';
def docker_allowed_branches = ['develop', master_branch_name, 'feature/ci'];
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
                            sh 'cp sample.env .env'
                            sh ". /py27; tox -e 'py27-security'"
                            sh 'rm .env'
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
                    sh "git checkout ${env.BRANCH_NAME}"
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
                        sh "git checkout develop"
                        sh "git merge ${master_branch_name}"
                        sshagent (credentials: ['JenkinsGitKey']) {
                            sh "git push develop --tags"
                        }
                        sh "git checkout ${master_branch_name}"
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
    }
}

