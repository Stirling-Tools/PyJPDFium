// pyjpdfium_native.cpp - nanobind binding over JPDFium's safe jpdf_* C API.
// Every native call runs with the GIL released; errors are raised after it is reacquired.

#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>

#include <cstdint>
#include <optional>
#include <string>
#include <tuple>

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
}
