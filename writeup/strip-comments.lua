-- strip-comments.lua
-- Remove raw HTML comments from the rendered output.
-- Quarto/pandoc passes <!-- ... --> blocks through as RawBlock('html')
-- or RawInline('html'); drop them so internal review notes don't ship.

local function is_html_comment(s)
  return s:match("^%s*<!%-%-") ~= nil
end

function RawBlock(el)
  if el.format == "html" and is_html_comment(el.text) then
    return {}
  end
end

function RawInline(el)
  if el.format == "html" and is_html_comment(el.text) then
    return {}
  end
end
