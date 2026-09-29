"""Shared completion truth from durable evidence, independent of mounted disks."""


def workflow_succeeded(copy, review, request, launch_error=None):
    reports = review.get('reports', [])
    return bool(
        copy.get('status') == 'completed' and copy.get('replicas_complete') is True
        and review.get('status') == 'completed' and not launch_error
        and isinstance(reports, list) and reports
        and len(reports) == len(request.get('replica_roots', []))
        and all(isinstance(r, dict) and r.get('status') == 'completed'
                and r.get('exit_code') == 0 and not r.get('missing_artifacts')
                and r.get('pdf_path') for r in reports)
    )
