#!/bin/bash
# Copia las etiquetas de cada Lambda a su log group (/aws/lambda/<función>).
# Salta las funciones sin etiquetas propias y las que aún no tienen log group.
REGION="${AWS_REGION:-eu-south-2}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws lambda list-functions --region $REGION --query 'Functions[].FunctionName' --output text | tr '\t' '\n' | while read -r FUNC; do
  FUNC_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNC}"

  TAGS_ARG=$(aws lambda list-tags --resource "$FUNC_ARN" --region $REGION --output json --query 'Tags' | python3 -c "
import json, sys
d = json.load(sys.stdin)
pairs = [f'{k}={v}' for k, v in d.items() if not k.startswith('aws:')]
print(','.join(pairs))
")

  if [ -z "$TAGS_ARG" ]; then
    echo "SKIP $FUNC — sin tags propios (solo reservados de AWS, o ninguno)"
    continue
  fi

  LOG_GROUP="/aws/lambda/${FUNC}"
  EXISTE=$(aws logs describe-log-groups --log-group-name-prefix "$LOG_GROUP" --region $REGION --query "logGroups[?logGroupName=='${LOG_GROUP}']" --output text)

  if [ -z "$EXISTE" ]; then
    echo "SKIP $FUNC — el log group aún no existe (nunca invocada)"
    continue
  fi

  echo "Tageando $LOG_GROUP con: $TAGS_ARG"
  aws logs tag-resource --resource-arn "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP}" --tags "$TAGS_ARG" --region $REGION
done
