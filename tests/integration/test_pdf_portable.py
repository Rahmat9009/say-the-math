"""Authored PDF regression checks: no downloaded papers, manifests or saved OCR.

Matplotlib and its installed fonts generate temporary test pages. Its renderer is
test-only; production discovery/rendering still use pdfplumber/PDFium.
"""
import base64
import hashlib
import io

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle
import pytest

from recognition import errors
from recognition.pdfnav import PDFNavigation
from recognition.service import ReaderService


@pytest.fixture(scope='module')
def authored_pdf():
    stream = io.BytesIO()
    with matplotlib.rc_context({'mathtext.fontset':'cm', 'pdf.fonttype':42}), PdfPages(stream) as pdf:
        fig = plt.figure(figsize=(6, 4))
        fig.text(.2, .72, r'$x+3=7$', fontsize=22)
        fig.text(.2, .32, r'$y^{2}=9$', fontsize=22)
        pdf.savefig(fig); plt.close(fig)
        fig = plt.figure(figsize=(6, 4))
        fig.text(.15, .5, 'This page contains only authored ordinary prose.', fontsize=12)
        pdf.savefig(fig); plt.close(fig)
        fig = plt.figure(figsize=(6, 4))
        fig.add_artist(Circle((.5,.5), .2, transform=fig.transFigure, fill=False))
        pdf.savefig(fig); plt.close(fig)
    return base64.b64encode(stream.getvalue()).decode('ascii')


@pytest.fixture
def navigation():
    service = ReaderService()
    nav = PDFNavigation(service)
    yield nav
    nav.clear()
    service.close()


def test_authored_pages_and_reading_order(navigation, authored_pdf):
    doc = navigation.open({'pdf_base64':authored_pdf, 'filename':'authored.pdf'})
    assert doc['page_count'] == 3
    assert [p['index'] for p in doc['pages']] == [0,1,2]
    assert [p['status'] for p in doc['pages']] == ['candidates','no_candidates','unsupported']
    assert doc['pages'][1]['announcement'].startswith('No candidates detected.')
    assert doc['pages'][2]['announcement'].startswith('Unsupported page.')
    assert all('no equations' not in p['announcement'].lower() for p in doc['pages'])
    regions = doc['equations']
    assert len(regions) == 2
    assert regions[0]['bbox_pt'][1] < regions[1]['bbox_pt'][1]
    assert [r['order'] for r in regions] == [0,1]
    assert all(r['region_completeness']['state']=='unknown' for r in regions)
    assert all(r['recognition']['status']=='pending' for r in regions)


def test_authored_preview_and_closed_session(navigation, authored_pdf):
    doc = navigation.open({'pdf_base64':authored_pdf})
    request = {'document_id':doc['document_id'], 'equation_id':doc['equations'][0]['id']}
    crop = navigation.crop(request)
    png = base64.b64decode(crop['image_base64'])
    assert png.startswith(b'\x89PNG\r\n\x1a\n')
    assert hashlib.sha256(png).hexdigest() == crop['crop_sha256']
    assert crop['region_completeness']['state'] == 'unknown'
    assert navigation.close({'document_id':doc['document_id']}) == {'closed':True}
    with pytest.raises(errors.ApiError) as stopped:
        navigation.crop(request)
    assert stopped.value.code == 'UNKNOWN_DOCUMENT'
