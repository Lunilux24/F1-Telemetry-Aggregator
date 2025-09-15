pipeline {
    agent any

    environment {
        BUCKET = credentials('S3Bucket')
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
                    credentialsId: 'gitPAT'
            }
        }

        stage('Install Dependencies') {
            steps {
                sh 'pip install -r requirements.txt'
            }
        }

        stage('Run Ingester with FastF1') {
            steps {
                sh 'python ingest/fastf1_ingest.py --bucket $BUCKET --region $AWS_REGION --include-fastf1'
            }
        }

        stage('Upload Logs to S3') {
            steps {
                sh 'aws s3 cp jenkins_logs.txt s3://$BUCKET/logs/$(date +%F_%H-%M-%S).log --region $AWS_REGION || true'
            }
        }
    }
}