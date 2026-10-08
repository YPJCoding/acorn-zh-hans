#!/usr/bin/env python3
"""
Acorn Localizer Core Engine (for AI Agent & Local CLI Workflow)
Provides deterministic diffing, validation, in-place patching, and restoration.
No bundling, no external dependencies, macOS native only.
"""

import argparse
import datetime
import hashlib
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

TOOL_VERSION = '1.0.0'
ROOT = Path(__file__).resolve().parent.parent
TRANSLATIONS_PATH = ROOT / 'translations/zh-Hans.json'
TERMBASE_PATH = ROOT / 'termbase.json'
DEFAULT_APP = Path('/Applications/Acorn.app')
BACKUP_DIR_NAME = '.acorn-zh-backup'
MANIFEST_NAME = 'acorn-zh-manifest.json'

FORMAT = re.compile(r'%(?:(\d+)\$)?([-+#0]*)(\d+|\*)?(?:\.(\d+|\*))?(hh|ll|[hlLzjt])?([@diuoxXfFeEgGaAcCsSpn%])')


class AcornToolError(Exception):
    """Custom exception for all Acorn tool errors."""
    pass


def run_cmd(args):
    result = subprocess.run([str(a) for a in args], text=True, capture_output=True)
    if result.returncode != 0:
        raise AcornToolError(f"Command failed ({args[0]}):\n{(result.stderr or result.stdout).strip()}")
    return result.stdout


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def load_plist_file(path):
    data = Path(path).read_bytes()
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        data = data.decode('utf-16').encode('utf-8')
    try:
        val = plistlib.loads(data)
    except Exception as exc:
        raise AcornToolError(f"Cannot parse plist at {path}: {exc}") from exc
    if not isinstance(val, dict):
        raise AcornToolError(f"Expected dict in plist: {path}")
    return val


def placeholder_signature(text):
    """Extract ordered format placeholders to guarantee printf argument safety."""
    tokens = []
    next_idx = 1
    for match in FORMAT.finditer(text):
        pos, flags, width, precision, length, kind = match.groups()
        if kind == '%':
            tokens.append(('literal', '%'))
            continue
        if width == '*' or precision == '*':
            tokens.append(('dynamic', match.group(0)))
            continue
        idx = int(pos) if pos else next_idx
        if not pos:
            next_idx += 1
        tokens.append((str(idx), flags, width or '', precision or '', length or '', kind))
    return sorted(tokens)


def validate_pair(key, value):
    if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
        raise AcornToolError(f"Translation must be non-empty string for key: {key!r}")
    if placeholder_signature(key) != placeholder_signature(value):
        raise AcornToolError(f"Format placeholder mismatch:\n  Key:   {key!r}\n  Value: {value!r}")
    for nl in ['\n', r'\n']:
        if key.count(nl) != value.count(nl):
            raise AcornToolError(f"Newline count mismatch for key: {key!r}")


class Dictionary:
    def __init__(self, path=TRANSLATIONS_PATH):
        self.path = Path(path)
        if not self.path.is_file():
            raise AcornToolError(f"Dictionary file missing: {self.path}")
        self.data = json.loads(self.path.read_text(encoding='utf-8'))
        if self.data.get('schema') != 1 or self.data.get('language') != 'zh-Hans':
            raise AcornToolError("Unsupported translation schema or language in dictionary")
        self.canonical = self.data.get('canonical', {})
        self.exact = self.data.get('exact', {})
        self._rebuild_folded()

    def _rebuild_folded(self):
        self.folded = {}
        for k, v in self.canonical.items():
            validate_pair(k, v)
            f = k.casefold()
            self.folded[f] = v
        for k, v in self.exact.items():
            validate_pair(k, v)

    def lookup(self, key):
        if key in self.exact:
            return self.exact[key], 'exact'
        if key.casefold() in self.folded:
            return self.folded[key.casefold()], 'canonical'
        match = re.fullmatch(r'(.*?)( \((?:Shift-)?[A-Z]\))?([:：]|…|\.\.\.)?', key, flags=re.DOTALL)
        if match:
            base, shortcut, punc = match.groups()
            base_val = self.folded.get(base.casefold())
            if base_val is not None:
                val = base_val + (shortcut or '') + ('：' if punc in (':', '：') else (punc or ''))
                validate_pair(key, val)
                return val, 'variant'
        return key, 'untranslated'

    def update_translations(self, new_entries, exact=False):
        """Update dictionary with a mapping of {key: value} and save."""
        target = self.exact if exact else self.canonical
        for k, v in new_entries.items():
            validate_pair(k, v)
            target[k] = v
        self._rebuild_folded()
        self.save()

    def save(self):
        self.data['canonical'] = dict(sorted(self.canonical.items()))
        self.data['exact'] = dict(sorted(self.exact.items()))
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def get_app_info(app_path):
    app = Path(app_path).expanduser().resolve()
    if not app.exists() or not app.is_dir() or app.suffix != '.app':
        raise AcornToolError(f"Target is not a valid .app bundle: {app}")
    info_path = app / 'Contents/Info.plist'
    if not info_path.exists():
        raise AcornToolError(f"Missing Info.plist in {app}")
    info = load_plist_file(info_path)
    bundle_id = info.get('CFBundleIdentifier', '')
    if not bundle_id.startswith('com.flyingmeat.Acorn'):
        raise AcornToolError(f"Bundle identifier {bundle_id} is not an Acorn application")
    return app, info


def check_running(app_path):
    target_bin = str(Path(app_path).resolve() / 'Contents/MacOS/Acorn')
    out = run_cmd(['/bin/ps', '-axo', 'pid=,comm='])
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1] == target_bin:
            raise AcornToolError(f"Acorn is currently running (PID {parts[0]}). Please quit it before continuing.")


def get_status(app_path):
    app, info = get_app_info(app_path)
    resources = app / 'Contents/Resources'
    backup_dir = resources / BACKUP_DIR_NAME
    manifest_file = resources / MANIFEST_NAME
    zh_dir = resources / 'zh-Hans.lproj'

    has_backup = backup_dir.is_dir() and (backup_dir / 'Acorn.bak').exists()
    has_manifest = manifest_file.exists()
    has_zh = zh_dir.is_dir() and (zh_dir / 'Localizable.strings').exists()

    if has_backup and has_zh:
        status_code = 'LOCALIZED'
    elif not has_backup and not has_zh:
        status_code = 'OFFICIAL'
    else:
        status_code = 'DIRTY'

    # Signature check
    sig_ok = True
    sig_err = ""
    try:
        run_cmd(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])
    except AcornToolError as exc:
        sig_ok = False
        sig_err = str(exc)

    return {
        'app_path': str(app),
        'version': info.get('CFBundleShortVersionString', 'unknown'),
        'build': info.get('CFBundleVersion', 'unknown'),
        'bundle_id': info.get('CFBundleIdentifier'),
        'status': status_code,
        'has_backup': has_backup,
        'has_zh_resource': has_zh,
        'signature_valid': sig_ok,
        'signature_error': sig_err if not sig_ok else None,
        'dev_region': info.get('CFBundleDevelopmentRegion'),
        'sparkle_disabled': (info.get('SUEnableAutomaticChecks') is False and info.get('SUAutomaticallyUpdate') is False)
    }


def scan_source_keys(app_path):
    app, _ = get_app_info(app_path)
    resources = app / 'Contents/Resources'
    all_keys = {}  # {key: {lang: val}}
    for strings_file in sorted(resources.glob('*.lproj/Localizable.strings')):
        lang = strings_file.parent.stem
        if lang.startswith('zh'):
            continue  # ignore generated/existing chinese
        try:
            table = load_plist_file(strings_file)
            for k, v in table.items():
                if isinstance(k, str) and isinstance(v, str):
                    all_keys.setdefault(k, {})[lang] = v
        except Exception:
            continue
    return all_keys


def calculate_diff(app_path, dictionary=None):
    if dictionary is None:
        dictionary = Dictionary()
    source_keys = scan_source_keys(app_path)
    translated = []
    untranslated = []

    for key, lang_map in sorted(source_keys.items()):
        val, status = dictionary.lookup(key)
        if status != 'untranslated':
            translated.append({
                'key': key,
                'translation': val,
                'status': status,
                'languages': list(lang_map.keys())
            })
        else:
            # Collect context references (German, French, Spanish, etc.)
            refs = {l: lang_map[l] for l in ['de', 'fr', 'es', 'it'] if l in lang_map}
            untranslated.append({
                'key': key,
                'references': refs,
                'placeholders': [m.group(0) for m in FORMAT.finditer(key) if m.group(0) != '%'],
                'has_newline': '\n' in key
            })

    return {
        'total_keys': len(source_keys),
        'translated_count': len(translated),
        'untranslated_count': len(untranslated),
        'coverage_percentage': round(len(translated) / len(source_keys) * 100, 2) if source_keys else 0,
        'untranslated': untranslated
    }


def apply_patch(app_path, dictionary=None):
    check_running(app_path)
    if dictionary is None:
        dictionary = Dictionary()

    app, info = get_app_info(app_path)
    resources = app / 'Contents/Resources'
    backup_dir = resources / BACKUP_DIR_NAME
    zh_dir = resources / 'zh-Hans.lproj'
    manifest_file = resources / MANIFEST_NAME

    # 1. Inspect existing state
    current_status = get_status(app_path)
    if current_status['status'] == 'LOCALIZED':
        # If already localized, restore first to have clean origin for re-patching
        restore_app(app_path)
        app, info = get_app_info(app_path)

    # 2. Check if clean official
    run_cmd(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])

    # 3. Create file-level backups (only the 3 affected files)
    files_to_backup = [
        ('Contents/Info.plist', 'Info.plist.bak'),
        ('Contents/MacOS/Acorn', 'Acorn.bak'),
        ('Contents/_CodeSignature/CodeResources', 'CodeResources.bak'),
    ]

    backup_dir.mkdir(parents=True, exist_ok=True)
    orig_hashes = {}
    for rel_src, bak_name in files_to_backup:
        src = app / rel_src
        dst = backup_dir / bak_name
        if not src.exists():
            raise AcornToolError(f"Required original file missing: {src}")
        shutil.copy2(src, dst)
        orig_hashes[rel_src] = sha256_file(src)

    # 4. Generate full localized table
    source_keys = scan_source_keys(app_path)
    all_keys = sorted(set(source_keys.keys()) | set(dictionary.canonical.keys()) | set(dictionary.exact.keys()))
    full_table = {}
    translated_count = 0
    for k in all_keys:
        val, status = dictionary.lookup(k)
        if status != 'untranslated':
            validate_pair(k, val)
            translated_count += 1
            full_table[k] = val
        else:
            full_table[k] = k

    # 5. Write zh-Hans.lproj/Localizable.strings
    zh_dir.mkdir(parents=True, exist_ok=True)
    strings_file = zh_dir / 'Localizable.strings'
    strings_file.write_bytes(plistlib.dumps(full_table, fmt=plistlib.FMT_XML, sort_keys=True))

    # 6. Update Info.plist
    info_path = app / 'Contents/Info.plist'
    patched_info = dict(info)
    patched_info['CFBundleDisplayName'] = 'Acorn'
    patched_info['CFBundleDevelopmentRegion'] = 'zh-Hans'
    existing_locales = [p.stem for p in resources.glob('*.lproj') if p.stem != 'Base']
    patched_info['CFBundleLocalizations'] = sorted(set(existing_locales) | {'zh-Hans'})
    patched_info['SUEnableAutomaticChecks'] = False
    patched_info['SUAutomaticallyUpdate'] = False
    info_path.write_bytes(plistlib.dumps(patched_info, fmt=plistlib.FMT_XML, sort_keys=True))

    # 7. Write manifest
    manifest_data = {
        'tool': 'acorn-zh-agent',
        'tool_version': TOOL_VERSION,
        'patched_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'source_version': info.get('CFBundleShortVersionString'),
        'source_build': info.get('CFBundleVersion'),
        'original_hashes': orig_hashes,
        'translated_entries': translated_count,
        'dictionary_hash': hashlib.sha256(json.dumps(dictionary.data, sort_keys=True).encode('utf-8')).hexdigest()
    }
    manifest_file.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    # 8. Re-sign outer bundle safely (preserve entitlements and hardened runtime)
    run_cmd([
        '/usr/bin/codesign',
        '--force',
        '--sign', '-',
        '--preserve-metadata=entitlements,flags,runtime',
        str(app)
    ])

    # 9. Verify signature
    run_cmd(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])

    return {
        'status': 'SUCCESS',
        'app_path': str(app),
        'translated_entries': translated_count,
        'total_entries': len(all_keys),
        'backup_location': str(backup_dir)
    }


def restore_app(app_path):
    check_running(app_path)
    app, _ = get_app_info(app_path)
    resources = app / 'Contents/Resources'
    backup_dir = resources / BACKUP_DIR_NAME
    manifest_file = resources / MANIFEST_NAME
    zh_dir = resources / 'zh-Hans.lproj'

    if not backup_dir.is_dir():
        raise AcornToolError("No backup directory found inside application. Cannot restore.")

    files_to_restore = [
        ('Info.plist.bak', 'Contents/Info.plist'),
        ('Acorn.bak', 'Contents/MacOS/Acorn'),
        ('CodeResources.bak', 'Contents/_CodeSignature/CodeResources'),
    ]

    for bak_name, rel_dst in files_to_restore:
        bak_file = backup_dir / bak_name
        if not bak_file.is_file():
            raise AcornToolError(f"Backup file missing: {bak_file}")
        shutil.copy2(bak_file, app / rel_dst)

    # Clean up added resources
    if zh_dir.exists():
        shutil.rmtree(zh_dir)
    if manifest_file.exists():
        manifest_file.unlink()
    shutil.rmtree(backup_dir)

    # Verify original signature
    run_cmd(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)])

    return {
        'status': 'RESTORED',
        'app_path': str(app),
        'message': 'Original files restored and original signature verified.'
    }


def main():
    parser = argparse.ArgumentParser(description="Acorn Localizer Core Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status
    p_status = subparsers.add_parser("status", help="Check status of target Acorn.app")
    p_status.add_argument("--app", default=str(DEFAULT_APP), help="Path to Acorn.app")
    p_status.add_argument("--json", action="store_true", help="Output JSON")

    # diff
    p_diff = subparsers.add_parser("diff", help="Calculate untranslated diff between Acorn and dictionary")
    p_diff.add_argument("--app", default=str(DEFAULT_APP), help="Path to Acorn.app")
    p_diff.add_argument("--output", help="Optional output JSON file path for diff items")
    p_diff.add_argument("--limit", type=int, default=0, help="Limit number of untranslated items displayed")

    # apply
    p_apply = subparsers.add_parser("apply", help="Apply localization in-place to target Acorn.app")
    p_apply.add_argument("--app", default=str(DEFAULT_APP), help="Path to Acorn.app")

    # restore
    p_restore = subparsers.add_parser("restore", help="Restore target Acorn.app to original official state")
    p_restore.add_argument("--app", default=str(DEFAULT_APP), help="Path to Acorn.app")

    args = parser.parse_args()

    try:
        if args.command == "status":
            res = get_status(args.app)
            if args.json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            else:
                print(f"Acorn App:       {res['app_path']}")
                print(f"Version:         {res['version']} (build {res['build']})")
                print(f"Status:          {res['status']}")
                print(f"Signature Valid: {res['signature_valid']}")
                print(f"Has Backup:      {res['has_backup']}")
                print(f"Chinese Active:  {res['has_zh_resource']}")

        elif args.command == "diff":
            res = calculate_diff(args.app)
            if args.output:
                Path(args.output).write_text(json.dumps(res['untranslated'], indent=2, ensure_ascii=False), encoding='utf-8')
                print(f"Wrote {len(res['untranslated'])} untranslated items to {args.output}")
            print(f"Total Unique Keys:     {res['total_keys']}")
            print(f"Translated Keys:       {res['translated_count']}")
            print(f"Untranslated Keys:     {res['untranslated_count']}")
            print(f"Coverage:              {res['coverage_percentage']}%")
            if res['untranslated'] and not args.output:
                limit = args.limit if args.limit > 0 else 5
                print(f"\nPreview of first {min(limit, len(res['untranslated']))} untranslated keys:")
                for item in res['untranslated'][:limit]:
                    print(f"  - Key: {item['key']!r}")
                    if item['references']:
                        print(f"    Refs: {item['references']}")
                    if item['placeholders']:
                        print(f"    Placeholders: {item['placeholders']}")

        elif args.command == "apply":
            print(f"Applying localization to {args.app} ...")
            res = apply_patch(args.app)
            print("Successfully localized Acorn!")
            print(f"  Translated entries: {res['translated_entries']} / {res['total_entries']}")
            print(f"  Backup directory:   {res['backup_location']}")

        elif args.command == "restore":
            print(f"Restoring {args.app} to original official state ...")
            res = restore_app(args.app)
            print("Successfully restored Acorn to official original state!")
            print(f"  {res['message']}")

    except AcornToolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
