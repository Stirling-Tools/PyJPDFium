// pyjpdfium_native.cpp - nanobind binding over JPDFium's safe jpdf_* C API.
// Every native call runs with the GIL released; errors are raised after it is reacquired.

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>

#include <algorithm>
#include <array>
#include <climits>
#include <cstdint>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

#include "jpdfium_api.h"

namespace nb = nanobind;

namespace {

// Must run on the failing thread before any other jpdf_* call; detail is per thread and call.
std::string last_error_detail() {
    uint64_t needed = 0;
    jpdf_last_error_message(nullptr, 0, &needed);
    if (needed <= 1) return {};
    std::string detail(static_cast<size_t>(needed), '\0');
    if (jpdf_last_error_message(detail.data(), needed, &needed) != JPDF_OK) return {};
    detail.pop_back();
    return detail;
}

[[noreturn]] void raise_status(jpdf_status status, const std::string& detail) {
    nb::object errors = nb::module_::import_("pyjpdfium.errors");
    nb::object exc = errors.attr("_from_status")(status, jpdf_status_name(status), detail);
    PyErr_SetObject(reinterpret_cast<PyObject*>(Py_TYPE(exc.ptr())), exc.ptr());
    throw nb::python_error();
}

template <typename Call>
void run(Call&& call) {
    jpdf_status status;
    std::string detail;
    {
        nb::gil_scoped_release release;
        status = call();
        if (status != JPDF_OK) detail = last_error_detail();
    }
    if (status != JPDF_OK) raise_status(status, detail);
}

jpdf_render_options render_options(uint32_t flags, double dpi_x, double dpi_y, int32_t width,
                                   int32_t height, int32_t pixel_format, uint64_t max_pixels) {
    jpdf_render_options o{};
    o.struct_size = sizeof(o);
    o.flags = flags;
    o.dpi_x = dpi_x;
    o.dpi_y = dpi_y;
    o.width = width;
    o.height = height;
    o.pixel_format = pixel_format;
    o.max_pixels = max_pixels;
    return o;
}

jpdf_write_options write_options(bool durable, int32_t png_compression, uint64_t max_bytes) {
    jpdf_write_options w{};
    w.struct_size = sizeof(w);
    w.flags = durable ? JPDF_WRITE_DURABLE : 0u;
    w.image_format = JPDF_IMAGE_PNG;
    w.png_compression = png_compression;
    w.max_bytes = max_bytes;
    return w;
}

bool struct_sizes_match() {
    const int64_t expected[][2] = {
        {JPDF_STRUCT_RUNTIME_OPTIONS, sizeof(jpdf_runtime_options)},
        {JPDF_STRUCT_RUNTIME_INFO, sizeof(jpdf_runtime_info)},
        {JPDF_STRUCT_OPEN_OPTIONS, sizeof(jpdf_open_options)},
        {JPDF_STRUCT_PAGE_INFO, sizeof(jpdf_page_info)},
        {JPDF_STRUCT_RENDER_OPTIONS, sizeof(jpdf_render_options)},
        {JPDF_STRUCT_BITMAP_INFO, sizeof(jpdf_bitmap_info)},
        {JPDF_STRUCT_BITMAP_VIEW, sizeof(jpdf_bitmap_view)},
        {JPDF_STRUCT_WRITE_OPTIONS, sizeof(jpdf_write_options)},
        {JPDF_STRUCT_RASTER_OPTIONS, sizeof(jpdf_raster_options)},
        {JPDF_STRUCT_RASTER_RESULT, sizeof(jpdf_raster_result)},
        {JPDF_STRUCT_RECTIFY_OPTIONS, sizeof(jpdf_rectify_options)},
        {JPDF_STRUCT_RECTIFY_RESULT, sizeof(jpdf_rectify_result)},
        {JPDF_STRUCT_TEXT_WORD, sizeof(jpdf_text_word)},
        {JPDF_STRUCT_TEXT_LINE, sizeof(jpdf_text_line)},
        {JPDF_STRUCT_TEXT_LAYER_OPTIONS, sizeof(jpdf_text_layer_options)},
        {JPDF_STRUCT_IMAGE_LOAD_OPTIONS, sizeof(jpdf_image_load_options)},
    };
    for (const auto& pair : expected) {
        if (jpdf_abi_struct_size(static_cast<int32_t>(pair[0])) != pair[1]) return false;
    }
    return true;
}

nb::dict runtime_info() {
    jpdf_runtime_info info{};
    info.struct_size = sizeof(info);
    run([&] { return jpdf_runtime_get_info(&info); });
    nb::dict d;
    d["state"] = info.state;
    d["api_version"] = nb::make_tuple(info.api_major, info.api_minor);
    d["renderer"] = info.renderer;
    d["build_id"] = info.build_id ? std::string(info.build_id) : std::string();
    d["live_documents"] = info.live_documents;
    d["live_pages"] = info.live_pages;
    d["live_bitmaps"] = info.live_bitmaps;
    d["live_views"] = info.live_views;
    d["domain_acquisitions"] = info.domain_acquisitions;
    d["domain_wait_ns"] = info.domain_wait_ns;
    d["domain_hold_ns"] = info.domain_hold_ns;
    return d;
}

nb::bytes bitmap_copy(jpdf_handle bitmap) {
    jpdf_bitmap_info info{};
    info.struct_size = sizeof(info);
    run([&] { return jpdf_bitmap_get_info(bitmap, &info); });
    PyObject* raw = PyBytes_FromStringAndSize(nullptr, static_cast<Py_ssize_t>(info.byte_size));
    if (!raw) throw nb::python_error();
    nb::bytes out = nb::steal<nb::bytes>(raw);
    char* dst = PyBytes_AS_STRING(raw);
    uint64_t written = 0;
    // The new bytes object is not shared yet, so filling it without the GIL is safe.
    run([&] {
        return jpdf_bitmap_copy_pixels(bitmap, reinterpret_cast<uint8_t*>(dst), info.byte_size,
                                       &written);
    });
    return out;
}

std::string page_text(jpdf_handle page) {
    uint64_t needed = 0;
    run([&] { return jpdf_page_get_text(page, nullptr, 0, &needed); });
    std::string text(static_cast<size_t>(needed), '\0');
    run([&] { return jpdf_page_get_text(page, text.data(), needed, &needed); });
    text.resize(text.empty() ? 0 : text.size() - 1);
    return text;
}

using Box = std::tuple<double, double, double, double>;
using Quad = std::array<double, 8>;

// Owned copies are built with the GIL held; the native call then only reads them.
void text_layer_write(const std::string& output, int32_t image_width, int32_t image_height,
                      double dpi_x, double dpi_y,
                      const std::vector<std::tuple<Box, int32_t, uint32_t, Quad>>& lines,
                      const std::vector<std::tuple<std::string, Box, uint32_t, Quad>>& words,
                      bool durable, uint64_t max_bytes) {
    jpdf_text_layer_options o{};
    o.struct_size = sizeof(o);
    o.image_width = image_width;
    o.image_height = image_height;
    o.dpi_x = dpi_x;
    o.dpi_y = dpi_y;
    o.font = JPDF_FONT_GLYPHLESS;
    std::vector<jpdf_text_line> native_lines(lines.size());
    for (size_t i = 0; i < lines.size(); ++i) {
        jpdf_text_line& l = native_lines[i];
        l.struct_size = sizeof(l);
        std::tie(l.x0, l.y0, l.x1, l.y1) = std::get<0>(lines[i]);
        l.word_count = std::get<1>(lines[i]);
        l.flags = std::get<2>(lines[i]);
        std::copy(std::get<3>(lines[i]).begin(), std::get<3>(lines[i]).end(), l.quad);
    }
    std::vector<jpdf_text_word> native_words(words.size());
    for (size_t i = 0; i < words.size(); ++i) {
        jpdf_text_word& w = native_words[i];
        w.struct_size = sizeof(w);
        w.text_utf8 = std::get<0>(words[i]).c_str();
        std::tie(w.x0, w.y0, w.x1, w.y1) = std::get<1>(words[i]);
        w.flags = std::get<2>(words[i]);
        std::copy(std::get<3>(words[i]).begin(), std::get<3>(words[i]).end(), w.quad);
    }
    if (native_lines.size() > INT32_MAX || native_words.size() > INT32_MAX) {
        throw nb::value_error("too many lines or words");
    }
    jpdf_write_options w{};
    w.struct_size = sizeof(w);
    w.flags = durable ? JPDF_WRITE_DURABLE : 0u;
    w.max_bytes = max_bytes;
    run([&] {
        return jpdf_text_layer_write(&o, native_lines.data(),
                                     static_cast<int32_t>(native_lines.size()), native_words.data(),
                                     static_cast<int32_t>(native_words.size()), output.c_str(), &w);
    });
}

using PixelArray = nb::ndarray<nb::memview, const uint8_t, nb::ro>;

size_t channels_for(int32_t pixel_format) {
    if (pixel_format == JPDF_PIXEL_RGBA8) return 4;
    if (pixel_format == JPDF_PIXEL_RGB8) return 3;
    return 1;
}

// The capsule owns the native view, so the memoryview keeps the pixels pinned on its own.
PixelArray bitmap_view(jpdf_handle bitmap) {
    jpdf_bitmap_view view{};
    view.struct_size = sizeof(view);
    run([&] { return jpdf_bitmap_map(bitmap, &view); });
    auto* token = new jpdf_handle(view.view);
    nb::capsule owner(token, [](void* p) noexcept {
        auto* h = static_cast<jpdf_handle*>(p);
        jpdf_view_release(*h);
        delete h;
    });
    const size_t channels = channels_for(view.pixel_format);
    const size_t shape[3] = {static_cast<size_t>(view.height), static_cast<size_t>(view.width),
                             channels};
    const int64_t strides[3] = {view.stride, static_cast<int64_t>(channels), 1};
    return PixelArray(view.data, channels == 1 ? 2 : 3, shape, owner, strides);
}

}  // namespace

NB_MODULE(_native, m) {
    m.doc() = "Low-level binding over jpdfium_api.h. Use the pyjpdfium package instead.";

    m.attr("COMPILED_API_VERSION") = (JPDF_API_VERSION_MAJOR << 16) | JPDF_API_VERSION_MINOR;
    nb::dict status;
    for (jpdf_status s : {JPDF_OK,
                          JPDF_E_INVALID_ARGUMENT,
                          JPDF_E_INVALID_HANDLE,
                          JPDF_E_STALE_HANDLE,
                          JPDF_E_WRONG_HANDLE_TYPE,
                          JPDF_E_BUSY,
                          JPDF_E_UNSUPPORTED,
                          JPDF_E_IO,
                          JPDF_E_PASSWORD,
                          JPDF_E_FORMAT,
                          JPDF_E_NOT_FOUND,
                          JPDF_E_LIMIT,
                          JPDF_E_NO_MEMORY,
                          JPDF_E_BUFFER_TOO_SMALL,
                          JPDF_E_NOT_INITIALIZED,
                          JPDF_E_QUIESCING,
                          JPDF_E_STOPPED,
                          JPDF_E_FAILED,
                          JPDF_E_AUTHORITY,
                          JPDF_E_REENTRANT,
                          JPDF_E_CANCELLED,
                          JPDF_E_TIMEOUT,
                          JPDF_E_INTERNAL}) {
        status[jpdf_status_name(s)] = s;
    }
    m.attr("STATUS") = status;

    m.def("api_version", [] { return jpdf_api_version(); });
    m.def("struct_sizes_match", &struct_sizes_match);
    m.def("capability", [](const std::string& name) {
        int32_t level = 0;
        run([&] { return jpdf_capability(name.c_str(), &level); });
        return level;
    });

    m.def("runtime_init", [](int32_t renderer) {
        jpdf_runtime_options o{};
        o.struct_size = sizeof(o);
        o.renderer = renderer;
        run([&] { return jpdf_runtime_init(&o); });
    });
    m.def("runtime_info", &runtime_info);
    m.def("runtime_quiesce", [] { run([] { return jpdf_runtime_quiesce(); }); });
    m.def("runtime_shutdown", [] { run([] { return jpdf_runtime_shutdown(); }); });

    m.def(
        "doc_open",
        [](const std::string& path, std::optional<std::string> password) {
            jpdf_open_options o{};
            o.struct_size = sizeof(o);
            o.password = password ? password->c_str() : nullptr;
            jpdf_handle doc = 0;
            run([&] { return jpdf_doc_open_file(path.c_str(), &o, &doc); });
            return doc;
        },
        nb::arg("path"), nb::arg("password").none());
    m.def("doc_close", [](jpdf_handle doc) { run([&] { return jpdf_doc_close(doc); }); });
    m.def("doc_page_count", [](jpdf_handle doc) {
        int32_t count = 0;
        run([&] { return jpdf_doc_page_count(doc, &count); });
        return count;
    });

    m.def("page_open", [](jpdf_handle doc, int32_t index) {
        jpdf_handle page = 0;
        run([&] { return jpdf_page_open(doc, index, &page); });
        return page;
    });
    m.def("page_close", [](jpdf_handle page) { run([&] { return jpdf_page_close(page); }); });
    m.def("page_info", [](jpdf_handle page) {
        jpdf_page_info info{};
        info.struct_size = sizeof(info);
        run([&] { return jpdf_page_get_info(page, &info); });
        return std::make_tuple(info.index, info.width_pt, info.height_pt, info.rotation);
    });

    m.def("page_text", &page_text);

    m.def("page_render", [](jpdf_handle page, uint32_t flags, double dpi_x, double dpi_y,
                            int32_t width, int32_t height, int32_t pixel_format,
                            uint64_t max_pixels) {
        jpdf_render_options o =
            render_options(flags, dpi_x, dpi_y, width, height, pixel_format, max_pixels);
        jpdf_handle bitmap = 0;
        run([&] { return jpdf_page_render(page, &o, &bitmap); });
        return bitmap;
    });
    m.def("page_render_to_file",
          [](jpdf_handle page, uint32_t flags, double dpi_x, double dpi_y, int32_t width,
             int32_t height, int32_t pixel_format, uint64_t max_pixels, const std::string& path,
             bool durable, int32_t png_compression, uint64_t max_bytes) {
              jpdf_render_options o =
                  render_options(flags, dpi_x, dpi_y, width, height, pixel_format, max_pixels);
              jpdf_write_options w = write_options(durable, png_compression, max_bytes);
              run([&] { return jpdf_page_render_to_file(page, &o, path.c_str(), &w); });
          });

    m.def("image_load", [](const std::string& path, uint64_t max_pixels) {
        jpdf_image_load_options o{};
        o.struct_size = sizeof(o);
        o.max_pixels = max_pixels;
        jpdf_handle bitmap = 0;
        run([&] { return jpdf_image_load_file(path.c_str(), &o, &bitmap); });
        return bitmap;
    });

    m.def("bitmap_info", [](jpdf_handle bitmap) {
        jpdf_bitmap_info info{};
        info.struct_size = sizeof(info);
        run([&] { return jpdf_bitmap_get_info(bitmap, &info); });
        return std::make_tuple(info.pixel_format, info.width, info.height, info.stride,
                               info.dpi_x, info.dpi_y, info.byte_size);
    });
    m.def("bitmap_copy", &bitmap_copy);
    m.def("bitmap_view", &bitmap_view);
    m.def("bitmap_write_file", [](jpdf_handle bitmap, const std::string& path, bool durable,
                                  int32_t png_compression, uint64_t max_bytes) {
        jpdf_write_options w = write_options(durable, png_compression, max_bytes);
        run([&] { return jpdf_bitmap_write_file(bitmap, path.c_str(), &w); });
    });
    m.def("bitmap_close",
          [](jpdf_handle bitmap) { run([&] { return jpdf_bitmap_close(bitmap); }); });
    m.def("bitmap_rectify", [](jpdf_handle bitmap, const std::vector<double>& quad, int32_t width,
                               int32_t height, int32_t interpolation, int32_t border,
                               uint64_t max_pixels) {
        if (quad.size() != 8) throw nb::value_error("quad needs 8 coordinates");
        jpdf_rectify_options o{};
        o.struct_size = sizeof(o);
        o.width = width;
        o.height = height;
        o.interpolation = interpolation;
        o.border = border;
        o.max_pixels = max_pixels;
        jpdf_rectify_result r{};
        r.struct_size = sizeof(r);
        jpdf_handle out = 0;
        run([&] { return jpdf_bitmap_rectify(bitmap, quad.data(), &o, &out, &r); });
        return std::make_tuple(out, std::vector<double>(r.quad, r.quad + 8),
                               std::vector<double>(r.to_source, r.to_source + 9));
    });

    m.def("text_layer_write", &text_layer_write, nb::arg("output"), nb::arg("image_width"),
          nb::arg("image_height"), nb::arg("dpi_x"), nb::arg("dpi_y"), nb::arg("lines"),
          nb::arg("words"), nb::arg("durable"), nb::arg("max_bytes"));

    m.def("rasterize_page_file",
          [](const std::string& path, int32_t page_index, int32_t device, double dpi_x,
             double dpi_y, double out_dpi_x, double out_dpi_y, int32_t rotation_ccw,
             uint32_t flags, uint64_t max_pixels, std::optional<std::string> password,
             const std::string& output, bool durable, int32_t png_compression,
             uint64_t max_bytes) {
              jpdf_raster_options o{};
              o.struct_size = sizeof(o);
              o.flags = flags;
              o.raster_dpi_x = dpi_x;
              o.raster_dpi_y = dpi_y;
              o.output_dpi_x = out_dpi_x;
              o.output_dpi_y = out_dpi_y;
              o.rotation_ccw = rotation_ccw;
              o.device = device;
              o.max_pixels = max_pixels;
              o.password = password ? password->c_str() : nullptr;
              jpdf_write_options w = write_options(durable, png_compression, max_bytes);
              jpdf_raster_result r{};
              r.struct_size = sizeof(r);
              run([&] {
                  return jpdf_rasterize_page_file(path.c_str(), page_index, &o, output.c_str(),
                                                  &w, &r);
              });
              return std::make_tuple(r.width, r.height, r.bits_per_pixel, r.dpi_x, r.dpi_y);
          },
          nb::arg("path"), nb::arg("page_index"), nb::arg("device"), nb::arg("dpi_x"),
          nb::arg("dpi_y"), nb::arg("out_dpi_x"), nb::arg("out_dpi_y"), nb::arg("rotation_ccw"),
          nb::arg("flags"), nb::arg("max_pixels"), nb::arg("password").none(), nb::arg("output"),
          nb::arg("durable"), nb::arg("png_compression"), nb::arg("max_bytes"));
}
