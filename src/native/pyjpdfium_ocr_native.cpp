// pyjpdfium_ocr_native.cpp - nanobind binding over jpdfium_ocr.h, loaded only when OCR is used.
// Native calls run with the GIL released; errors come from the core's per-thread detail.

#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>

#include <array>
#include <string>
#include <tuple>
#include <vector>

#include "jpdfium_api.h"
#include "jpdfium_ocr.h"

namespace nb = nanobind;

namespace {

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

bool struct_sizes_match() {
    const int64_t expected[][2] = {
        {JPDF_OCR_STRUCT_OPTIONS, sizeof(jpdf_ocr_options)},
        {JPDF_OCR_STRUCT_ENGINE_INFO, sizeof(jpdf_ocr_engine_info)},
        {JPDF_OCR_STRUCT_RECOGNIZE_OPTIONS, sizeof(jpdf_ocr_recognize_options)},
        {JPDF_OCR_STRUCT_RESULT_INFO, sizeof(jpdf_ocr_result_info)},
        {JPDF_OCR_STRUCT_LINE, sizeof(jpdf_ocr_line)},
    };
    for (const auto& pair : expected) {
        if (jpdf_ocr_abi_struct_size(static_cast<int32_t>(pair[0])) != pair[1]) return false;
    }
    return true;
}

using Line = std::tuple<std::string, std::vector<double>, double, double>;
using Recognized = std::tuple<int32_t, int32_t, double, double, std::vector<Line>>;

// Reads a whole result; on failure the detail is captured before the result is closed.
jpdf_status read_result(jpdf_handle result, jpdf_ocr_result_info* info, std::vector<Line>* lines) {
    jpdf_status st = jpdf_ocr_result_get_info(result, info);
    for (int32_t i = 0; st == JPDF_OK && i < info->line_count; ++i) {
        jpdf_ocr_line line{};
        line.struct_size = sizeof(line);
        uint64_t needed = 0;
        st = jpdf_ocr_result_get_line(result, i, &line, nullptr, 0, &needed);
        if (st != JPDF_OK) break;
        std::string text(static_cast<size_t>(needed), '\0');
        st = jpdf_ocr_result_get_line(result, i, &line, text.data(), needed, &needed);
        if (st != JPDF_OK) break;
        text.pop_back();
        lines->emplace_back(std::move(text), std::vector<double>(line.polygon, line.polygon + 8),
                            line.confidence, line.detection_score);
    }
    return st;
}

// Recognizes and reads the result in one released-GIL section, then closes it.
Recognized recognize(jpdf_handle engine, jpdf_handle bitmap, uint64_t max_pixels) {
    jpdf_ocr_recognize_options o{};
    o.struct_size = sizeof(o);
    o.max_pixels = max_pixels;
    jpdf_ocr_result_info info{};
    info.struct_size = sizeof(info);
    std::vector<Line> lines;
    jpdf_status status;
    std::string detail;
    {
        nb::gil_scoped_release release;
        jpdf_handle result = 0;
        status = jpdf_ocr_recognize(engine, bitmap, &o, &result);
        if (status == JPDF_OK) {
            status = read_result(result, &info, &lines);
            if (status != JPDF_OK) detail = last_error_detail();
            jpdf_ocr_result_close(result);
        } else {
            detail = last_error_detail();
        }
    }
    if (status != JPDF_OK) raise_status(status, detail);
    return {info.image_width, info.image_height, info.dpi_x, info.dpi_y, std::move(lines)};
}

}  // namespace

NB_MODULE(_ocr_native, m) {
    m.doc() = "Low-level binding over jpdfium_ocr.h. Use pyjpdfium.ocr instead.";
    m.attr("COMPILED_API_VERSION") = (JPDF_OCR_API_VERSION_MAJOR << 16) | JPDF_OCR_API_VERSION_MINOR;
    m.def("api_version", [] { return jpdf_ocr_api_version(); });
    m.def("struct_sizes_match", &struct_sizes_match);
    m.def("capability", [](const std::string& name) {
        int32_t level = 0;
        run([&] { return jpdf_ocr_capability(name.c_str(), &level); });
        return level;
    });
    m.def("engine_open", [](const std::string& profile_dir, int32_t threads) {
        jpdf_ocr_options o{};
        o.struct_size = sizeof(o);
        o.profile_dir_utf8 = profile_dir.c_str();
        o.intra_op_threads = threads;
        jpdf_handle engine = 0;
        run([&] { return jpdf_ocr_engine_open(&o, &engine); });
        return engine;
    });
    m.def("engine_info", [](jpdf_handle engine) {
        jpdf_ocr_engine_info info{};
        info.struct_size = sizeof(info);
        run([&] { return jpdf_ocr_engine_get_info(engine, &info); });
        return std::make_tuple(std::string(info.profile_id), std::string(info.runtime_version));
    });
    m.def("engine_close", [](jpdf_handle engine) { run([&] { return jpdf_ocr_engine_close(engine); }); });
    m.def("recognize", &recognize);
}
