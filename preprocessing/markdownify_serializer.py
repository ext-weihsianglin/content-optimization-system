"""Default Markdown serializer: python-markdownify over provenance-owned blocks.

Markdownify owns Markdown traversal, headings, emphasis, deletion, lists and quotes.
Our converters preserve code whitespace, media targets and authoritative HTML where
plain Markdown is lossy. Source references are never derived from serialized text.
"""
from collections import defaultdict
from html import escape as html_escape
import re

from bs4 import BeautifulSoup, NavigableString
from markdownify import MarkdownConverter

SERIALIZER_VERSION = 'markdownify-structured-v1'
MARKDOWNIFY_VERSION = '1.2.3'
OPTIONS = {'heading_style': 'ATX', 'bullets': '-', 'newline_style': 'BACKSLASH',
           'autolinks': False, 'strip_pre': None, 'sub_symbol': '<sub>', 'sup_symbol': '<sup>'}


def target(value):
    for character, encoded in [('<', '%3C'), ('>', '%3E'), ('\n', '%0A'), ('\r', '%0D'), ('\t', '%09'), ('\\', '%5C')]:
        value = value.replace(character, encoded)
    return value


class FidelityConverter(MarkdownConverter):
    def escape(self, text, parent_tags):
        # markdownify escapes emphasis; also protect literal source syntax.
        text = text.replace('\\', '\\\\')
        text = super().escape(text, parent_tags)
        return re.sub(r'([`{}\[\]<>#!|])', r'\\\1', text)

    def process_tag(self, node, parent_tags=None):
        # No conversion through a flattened child string for these structures.
        if node.name in {'table', 'dl'}:
            return '\n\n' + str(node) + '\n\n'
        if node.name == 'ol' and not 0 <= int(node.get('start', 1)) <= 999999999:
            # CommonMark ordered markers cannot express these source starts.
            return '\n\n' + str(node) + '\n\n'
        if node.name == 'pre':
            return self.convert_pre(node, node.get_text(), parent_tags or set())
        if node.name in {'code', 'kbd', 'samp'}:
            return self.convert_code(node, node.get_text(), parent_tags or set())
        return super().process_tag(node, parent_tags)

    def convert__document_(self, el, text, parent_tags):
        text = text.strip('\n')
        # Keep an explicit terminal <br>, including break-only paragraphs.
        trailing = re.search(r'\\+$', text)
        if trailing and len(trailing[0]) % 2:
            text += '\n'
        return text

    def convert_code(self, el, text, parent_tags):
        if 'pre' in parent_tags:
            return text
        if not text or '\n' in text or '\r' in text or not text.strip():
            return f'<{el.name}>{html_escape(text)}</{el.name}>'
        delimiter = '`' * (1 + max(map(len, re.findall(r'`+', text)), default=0))
        padding = ' ' if text.startswith(('`', ' ')) or text.endswith(('`', ' ')) else ''
        return delimiter + padding + text + padding + delimiter

    convert_kbd = convert_code
    convert_samp = convert_code
    convert_strike = MarkdownConverter.convert_del

    def convert_pre(self, el, text, parent_tags):
        delimiter = '`' * max(3, 1 + max(map(len, re.findall(r'`+', text)), default=0))
        language = el.get('data-code-language', '')
        return f'\n\n{delimiter}{language}\n{text}' + ('' if text.endswith('\n') else '\n') + delimiter + '\n\n'

    def convert_a(self, el, text, parent_tags):
        if not el.has_attr('href'):
            return text
        return f'[{text}](<{target(el["href"])}>)'

    def convert_img(self, el, text, parent_tags):
        if not el.get('src'):
            return str(el)
        alt = self.escape(el.get('alt', ''), parent_tags)
        return f'![{alt}](<{target(el["src"])}>)'

    def convert_br(self, el, text, parent_tags):
        if not any(getattr(sibling, 'name', None) or str(sibling).strip() for sibling in el.next_siblings):
            # CommonMark does not render a hard-break marker at a paragraph end.
            return '<br>'
        return '\\\n'

    def convert_p(self, el, text, parent_tags):
        # Unlike the library default, retain explicit break-only content.
        text = text.strip(' \t\r')
        return '\n\n' + text + '\n\n' if text else ''


CONVERTER = FidelityConverter(**OPTIONS)


def _append_inline(soup, parent, nodes):
    for node in nodes:
        if node['type'] == 'text':
            parent.append(NavigableString(node['text']))
            continue
        tag = node.get('tag') or {'hard_break': 'br', 'inline_code': 'code', 'deletion': 'del',
                                 'inline_image': 'img', 'link': 'a', 'strong': 'strong', 'emphasis': 'em'}.get(node['type'], 'span')
        element = soup.new_tag(tag, attrs=dict(node.get('attributes', {})))
        if node['type'] == 'inline_image':
            if node.get('target'):
                element['src'] = node['resolved_target']
            element['alt'] = node.get('text', '')
        elif node['type'] == 'link' and 'target' in node:
            element['href'] = node['resolved_target']
        if node['type'] == 'inline_code':
            element.append(NavigableString(node['text']))
        else:
            _append_inline(soup, element, node.get('children', []))
        parent.append(element)


def serialize_inline(nodes):
    soup = BeautifulSoup('', 'html.parser')
    wrapper = soup.new_tag('span')
    _append_inline(soup, wrapper, nodes)
    return CONVERTER.process_tag(wrapper).strip(' ')


def blocks_to_soup(blocks):
    soup = BeautifulSoup('', 'html.parser', preserve_whitespace_tags={'pre', 'textarea', 'code', 'kbd'})
    children = defaultdict(list)
    for block in blocks:
        children[block.get('parent_id')].append(block)

    def append(block, parent):
        kind = block['type']
        if kind in {'table', 'definition_list'}:
            raw = block['table']['html'] if kind == 'table' else block['html']
            fragment = BeautifulSoup(raw, 'html.parser', preserve_whitespace_tags={'pre', 'textarea', 'code', 'kbd'})
            for element in list(fragment.contents):
                parent.append(element.extract())
            return
        name = {'heading': f'h{block.get("heading_level", 1)}', 'paragraph': 'p',
                'code': 'pre', 'image': 'img', 'list': 'ol' if block.get('ordered') else 'ul',
                'list_item': 'li', 'quote': 'blockquote', 'thematic_break': 'hr',
                'definition_term': 'dt', 'definition_description': 'dd'}.get(kind, 'div')
        element = soup.new_tag(name)
        if kind == 'list' and block.get('ordered'):
            element['start'] = str(block.get('start', 1))
        if kind == 'code':
            element['data-code-language'] = block.get('language', '')
            element.append(NavigableString(block.get('text', '')))
        elif kind == 'image':
            element['src'] = block.get('resolved_target', '')
            element['alt'] = block.get('text', '')
        elif 'inline_nodes' in block:
            _append_inline(soup, element, block['inline_nodes'])
        else:
            # Legacy flattened blocks stay source-derived; never parse cached
            # Markdown as HTML or invent missing annotations.
            element.append(NavigableString(block.get('text', '')))
        for child in children[block['block_id']]:
            append(child, element)
        parent.append(element)

    for block in children[None]:
        append(block, soup)
    return soup


def serialize_blocks(blocks):
    return CONVERTER.convert_soup(blocks_to_soup(blocks))
