@app.route(
    "/api",
    methods=["GET"],
)
def endpoint(
    request: Request,
    *,
    verbose: bool = False,
) -> Response:
    return handle(request)
