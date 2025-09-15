pipeline {
    agent any

    environment {
        // This pulls the S3 bucket name from Jenkins credentials (Secret text)
        BUCKET = credentials('b31790df-ecc3-49f8-babd-c04beea8bdaf') // Jenkins credentials
        AWS_REGION = 'us-west-2'
    }

    triggers {
        cron('0 12 * * *') // Run every day at noon
    }

    stages {
        stage('Checkout') {
            steps {
                git branch: 'main',
                    url: 'https://github.com/Lunilux24/F1-Telemetry-Aggregator.git',
                    credentialsId: '21bdc7ca-43b0-4bdc-920c-4a9f24fe0b4e'
            }
        }

        stage('Install Dependencies') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run Ingester with FastF1') {
            steps {
                sh 'python injest/fastf1_ingest.py --bucket $BUCKET --region $AWS_REGION --include-fastf1'
            }
        }

        stage('Upload Logs to S3') {
            steps {
                sh 'aws s3 cp jenkins_logs.txt s3://$BUCKET/logs/$(date +%F_%H-%M-%S).log --region $AWS_REGION || true'
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: '**/jenkins_logs.txt', onlyIfSuccessful: false
        }
    }
}