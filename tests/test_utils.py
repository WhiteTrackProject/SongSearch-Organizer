from songsearch.core.utils import render_template

def test_render_template_no_traversal():
    tpl = "{Artista}/{Álbum}"
    meta = {"Artista": "..", "Álbum": "Album"}
    result = render_template(tpl, meta)
    assert ".." not in result
