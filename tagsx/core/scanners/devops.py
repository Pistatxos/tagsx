"""Scanners de CI/CD e infraestructura como codigo: cloudformation,
codebuild, codepipeline, codecommit, ecr."""

from .common import emit


def scan_untagged_cloudformation(sesion, region, account, seen_arns):
    client = sesion.client("cloudformation", region_name=region)
    paginator = client.get_paginator("list_stacks")
    active_statuses = [
        "CREATE_COMPLETE", "CREATE_IN_PROGRESS", "CREATE_FAILED",
        "ROLLBACK_COMPLETE", "ROLLBACK_IN_PROGRESS", "ROLLBACK_FAILED",
        "UPDATE_COMPLETE", "UPDATE_IN_PROGRESS", "UPDATE_ROLLBACK_COMPLETE",
        "UPDATE_ROLLBACK_IN_PROGRESS", "UPDATE_ROLLBACK_FAILED",
        "IMPORT_COMPLETE", "IMPORT_IN_PROGRESS", "IMPORT_ROLLBACK_COMPLETE",
        "IMPORT_ROLLBACK_IN_PROGRESS", "IMPORT_ROLLBACK_FAILED",
    ]
    for page in paginator.paginate(StackStatusFilter=active_statuses):
        for stack in page.get("StackSummaries", []):
            item = emit(stack["StackId"], seen_arns)
            if item:
                yield item


def scan_untagged_codebuild(sesion, region, account, seen_arns):
    client = sesion.client("codebuild", region_name=region)
    names = client.list_projects().get("projects", [])
    for name in names:
        item = emit(f"arn:aws:codebuild:{region}:{account}:project/{name}", seen_arns)
        if item:
            yield item


def scan_untagged_codepipeline(sesion, region, account, seen_arns):
    client = sesion.client("codepipeline", region_name=region)
    paginator = client.get_paginator("list_pipelines")
    for page in paginator.paginate():
        for pipeline in page.get("pipelines", []):
            item = emit(f"arn:aws:codepipeline:{region}:{account}:{pipeline['name']}", seen_arns)
            if item:
                yield item


def scan_untagged_codecommit(sesion, region, account, seen_arns):
    client = sesion.client("codecommit", region_name=region)
    paginator = client.get_paginator("list_repositories")
    for page in paginator.paginate():
        for repo in page.get("repositories", []):
            item = emit(f"arn:aws:codecommit:{region}:{account}:{repo['repositoryName']}", seen_arns)
            if item:
                yield item


def scan_untagged_ecr(sesion, region, account, seen_arns):
    client = sesion.client("ecr", region_name=region)
    paginator = client.get_paginator("describe_repositories")
    for page in paginator.paginate():
        for repo in page.get("repositories", []):
            item = emit(repo["repositoryArn"], seen_arns)
            if item:
                yield item


SCANNERS = {
    "cloudformation": scan_untagged_cloudformation,
    "codebuild": scan_untagged_codebuild,
    "codepipeline": scan_untagged_codepipeline,
    "codecommit": scan_untagged_codecommit,
    "ecr": scan_untagged_ecr,
}
