"""pix2tex on local CPU: verified checkpoints, three-scale reading, raw mean token log probability.

The image-resizer loop and decoding follow pix2tex 0.1.4 (MIT, (c) Lukas Blecher) LatexOCR.__call__;
scoring follows the research ScoredOCR: the generated sequence is teacher-forced through decoder.net
and log_softmax of the original logits is averaged over generated tokens up to and including EOS.
"""
import hashlib
import os
import threading
import time
from pathlib import Path

os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('NO_ALBUMENTATIONS_UPDATE', '1')

import warnings

from PIL import Image

from . import config

# Keep Hugging Face libraries away from the user's global cache; nothing is downloaded at runtime.
os.environ.setdefault('HF_HOME', str(config.MODELS_DIR / 'hf-home'))
warnings.filterwarnings('ignore', message='Pydantic serializer warnings')
warnings.filterwarnings('ignore', category=UserWarning, module=r'albumentations\..*')


class ModelMissing(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_problems(models_dir: Path = None, verify_hash: bool = True):
    """Return a list of human-readable problems with the local checkpoints (empty when usable)."""
    models_dir = Path(models_dir or config.MODELS_DIR)
    problems = []
    for name, spec in config.CHECKPOINTS.items():
        p = models_dir / name
        if not p.is_file():
            problems.append(f'{name} is missing')
        elif verify_hash and sha256_file(p) != spec['sha256']:
            problems.append(f'{name} does not match its pinned SHA256')
    return problems


def minmax_size(img, max_dimensions=None, min_dimensions=None):
    """pix2tex.cli.minmax_size (copied to avoid importing pix2tex.cli, which pulls in GUI/clipboard modules)."""
    import numpy as np
    if max_dimensions is not None:
        ratios = [a / b for a, b in zip(img.size, max_dimensions)]
        if any(r > 1 for r in ratios):
            size = np.array(img.size) // max(ratios)
            img = img.resize(tuple(size.astype(int)), Image.BILINEAR)
    if min_dimensions is not None:
        padded_size = [max(img_dim, min_dim) for img_dim, min_dim in zip(img.size, min_dimensions)]
        if padded_size != list(img.size):
            padded_im = Image.new('L', padded_size, 255)
            padded_im.paste(img, img.getbbox())
            img = padded_im
    return img


class Pix2TexReader:
    def __init__(self, models_dir: Path = None):
        self.models_dir = Path(models_dir or config.MODELS_DIR)
        self.loaded = False
        self.load_seconds = None
        self.parameters = None
        self._load_lock = threading.Lock()
        self._job = threading.local()  # current CancelToken for the inference thread

    def load(self):
        with self._load_lock:
            if self.loaded:
                return
            problems = checkpoint_problems(self.models_dir)
            if problems:
                raise ModelMissing('; '.join(problems))
            t0 = time.perf_counter()
            import torch
            import yaml
            from munch import Munch
            import pix2tex
            from pix2tex.utils import parse_args
            from pix2tex.models import get_model
            from timm.models.resnetv2 import ResNetV2
            from timm.models.layers import StdConv2dSame
            from transformers import PreTrainedTokenizerFast

            torch.set_num_threads(config.TORCH_THREADS)
            pkg = Path(pix2tex.__file__).resolve().parent / 'model'
            with open(pkg / 'settings' / 'config.yaml', 'r', encoding='utf-8') as f:
                params = yaml.load(f, Loader=yaml.FullLoader)
            args = parse_args(Munch(params))
            args.update(no_cuda=True, no_resize=False, wandb=False, device='cpu', temperature=config.TEMPERATURE)
            model = get_model(args)
            state = torch.load(self.models_dir / 'weights.pth', map_location='cpu', weights_only=True)
            model.load_state_dict(state)
            model.eval()
            resizer = ResNetV2(layers=[2, 3, 3], num_classes=max(args.max_dimensions) // 32, global_pool='avg', in_chans=1,
                               drop_rate=.05, preact=True, stem_type='same', conv_layer=StdConv2dSame).to('cpu')
            resizer.load_state_dict(torch.load(self.models_dir / 'image_resizer.pth', map_location='cpu', weights_only=True))
            resizer.eval()
            tokenizer = PreTrainedTokenizerFast(tokenizer_file=str(pkg / 'dataset' / 'tokenizer.json'))

            count = lambda m: sum(p.numel() for p in m.parameters())
            self.parameters = {'encoder': count(model.encoder), 'decoder': count(model.decoder),
                               'image_resizer': count(resizer)}
            self.parameters['total'] = sum(self.parameters.values())
            if self.parameters['total'] > config.MAX_PARAMETERS:
                raise RuntimeError('Loaded model exceeds the 500M parameter limit')
            # Cancellation/time-limit check before every forward pass (one decoder pass per generated token).
            # Hooks only observe; they never change inputs, so readings are numerically unchanged.
            for module in (model.encoder, model.decoder.net, resizer):
                module.register_forward_pre_hook(self._check_stop)
            self.torch, self.args, self.model, self.resizer, self.tokenizer = torch, args, model, resizer, tokenizer
            self.load_seconds = time.perf_counter() - t0
            self.loaded = True

    def _check_stop(self, module, inputs):
        token = getattr(self._job, 'token', None)
        if token is not None:
            token.check()

    def predict(self, img: Image.Image):
        """One pix2tex reading -> (latex, raw mean token log probability)."""
        import numpy as np
        import torch.nn.functional as F
        from pix2tex.utils import pad, post_process, token2str
        from pix2tex.dataset.transforms import test_transform
        torch, args = self.torch, self.args
        # OpenMP's effective thread setting can differ in later HTTP worker threads.
        # Apply the configured budget on the thread doing inference, not just loading.
        torch.set_num_threads(config.TORCH_THREADS)
        img = minmax_size(pad(img), args.max_dimensions, args.min_dimensions)
        with torch.no_grad():
            input_image = img.convert('RGB').copy()
            r, w, h = 1, input_image.size[0], input_image.size[1]
            for _ in range(10):
                h = int(h * r)
                img = pad(minmax_size(input_image.resize((w, h), Image.Resampling.BILINEAR if r > 1 else Image.Resampling.LANCZOS),
                                      args.max_dimensions, args.min_dimensions))
                t = test_transform(image=np.array(img.convert('RGB')))['image'][:1].unsqueeze(0)
                w = (self.resizer(t).argmax(-1).item() + 1) * 32
                if w == img.size[0]:
                    break
                r = w / img.size[0]
            enc = self.model.encoder(t)
            bos = torch.LongTensor([[args.bos_token]])
            dec = self.model.decoder.generate(bos, args.max_seq_len, eos_token=args.eos_token, context=enc,
                                              temperature=config.TEMPERATURE)
            seq = torch.cat([bos, dec], dim=1)
            logits = self.model.decoder.net(seq[:, :-1], context=enc)
            lp = F.log_softmax(logits, dim=-1).gather(-1, seq[:, 1:, None])[0, :, 0]
            toks = seq[0, 1:].tolist()
            n = toks.index(args.eos_token) + 1 if args.eos_token in toks else len(toks)
            lp = lp[:n]
        pred = post_process(token2str(dec, self.tokenizer)[0])
        return pred, float(lp.mean())

    def read_scales(self, img: Image.Image, token=None):
        """Read the image at each configured scale (Lanczos). Returns a list of reads.

        token: optional jobs.CancelToken. Checked between scales and before every model forward pass; raises
        jobs.RecognitionStopped so a cancelled or timed-out reading stops instead of finishing in the background.
        """
        self.load()
        if token is not None:
            token.check()
        reads = []
        self._job.token = token
        try:
            for s in config.SCALES:
                if token is not None:
                    token.check()
                reads.append(self._read_one(img, s))
        finally:
            self._job.token = None
        return reads

    def _read_one(self, img, s):
        im = img if s == 1.0 else img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))),
                                             Image.Resampling.LANCZOS)
        t0 = time.perf_counter()
        latex, lp_mean = self.predict(im)
        return {'scale': s, 'latex': latex, 'lp_mean': lp_mean, 'seconds': time.perf_counter() - t0}
