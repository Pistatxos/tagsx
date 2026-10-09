# Configuración de tagsx. La lee igual la terminal que la web (Ajustes la reescribe
# conservando estos comentarios). Solo valores literales: la web no ejecuta el fichero.

# Perfil de ~/.aws/credentials o ~/.aws/config ("" = el de por defecto o AWS_PROFILE)
perfil_aws = ""

# Región(es) a escanear. Lo global (IAM, CloudFront, Route 53) se lee siempre aparte,
# en us-east-1. En la terminal se puede sobreescribir con AWS_REGIONS=eu-west-1,eu-south-2
regiones = ["eu-south-2"]

# Servicios que se escanean con su propia API (List/Describe) para ver también lo que
# nunca se ha etiquetado. Es la lista «predeterminados»: «todos» usa todos los que
# tienen escáner. Los que no estén aquí solo se ven si ya tienen alguna etiqueta.
servicios = [
    "ec2",
    "lambda",
    "rds",
    "s3",
    "dynamodb",
    "apigateway",
    "apigatewayv2",
    "sns",
    "sqs",
    "events",
    "secretsmanager",
    "ssm",
    "cloudwatch",
    "cloudformation",
    "elasticloadbalancing",
    "iam",
]

# El esquema de etiquetas: las columnas fijas de la tabla y del CSV/XLSX
esquema = [
    "Name",
    "Application",
    "Environment",
    "Owner",
    "Project",
    "Service",
    "ManagedBy",
]

# Valores conocidos por etiqueta. Solo avisan (y se sugieren al escribir): no bloquean.
catalogos = {
    "Environment": ["dev", "stg", "prod"],
    "ManagedBy": ["terraform", "cloudformation", "cdk", "serverless", "ansible", "manual"],
}

# True: los valores del esquema van en minúscula (salvo Name). La terminal los pasa a
# minúscula al cargar el CSV; la web avisa y tiene «Pasar a minúsculas».
minusculas = True
