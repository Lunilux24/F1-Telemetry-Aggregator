pipeline {
    agent any

    environment {
        BUCKET = credentials('S3Bucket')
        AWS_REGION = 'us-west-2'
        AWS_ACCESS_KEY_ID = credentials('IAM-AK')
        AWS_SECRET_ACCESS_KEY = credentials('IAM-SAK')
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

        stage('Install and Run') {
            steps {
                sh '''
                  python3 -m venv venv
                  . venv/bin/activate
                  pip install --upgrade pip
                  pip install -r requirements.txt
                  mkdir -p /tmp/f1_cache
                  python ingest/fastf1_ingest.py --bucket $BUCKET --region $AWS_REGION --include-fastf1
                '''
            }
        }

        stage('Upload Logs to S3') {
            steps {
                sh 'aws s3 cp jenkins_logs.txt s3://$BUCKET/logs/$(date +%F_%H-%M-%S).log --region $AWS_REGION || true'
            }
        }
    }
}