"""Isolated UI fixture: real template/assets, no project or geodata writes."""
from pathlib import Path
from flask import Flask, render_template, request
from routes.map import _fallback_context, bp

root = Path(__file__).resolve().parents[1]
app = Flask(__name__, template_folder=str(root / 'templates'), static_folder=str(root / 'static'))
app.register_blueprint(bp)


@app.get('/')
def preview():
    context = _fallback_context()
    context.update(
        server_error=False, server_error_msg='', server_error_detail='',
        dataset_api_enabled=False, editor_enabled=False, dataset_export_enabled=False,
        mapbox_token='', mapbox_token_present=False, style_token_mismatch=True,
        zoom=int(request.args.get('zoom', 17)),
        ui=dict(show_toolbar=True, show_dataset_button=True, show_editor_button=False),
    )
    return render_template('map.html', **context)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8090)
