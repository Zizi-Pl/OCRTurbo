import 'dart:convert';

import 'package:flet/flet.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_document_scanner/google_mlkit_document_scanner.dart';

/// Usluga Flet otwierajaca systemowy skaner dokumentow Google (ML Kit).
///
/// Metoda "scan" zwraca JSON:
///   {"status": "ok", "images": [...sciezki JPG...], "pdf": "...sciezka|null"}
///   {"status": "cancelled"}
///   {"status": "unsupported"}
///   {"status": "error", "error": "..."}
class DocScannerService extends FletService {
  DocScannerService({required super.control});

  @override
  void init() {
    super.init();
    control.addInvokeMethodListener(_invokeMethod);
  }

  Future<dynamic> _invokeMethod(String name, dynamic args) async {
    switch (name) {
      case "scan":
        return await _scan(args);
      default:
        throw Exception("Unknown DocScanner method: $name");
    }
  }

  Future<String> _scan(dynamic args) async {
    if (kIsWeb || defaultTargetPlatform != TargetPlatform.android) {
      return jsonEncode({"status": "unsupported"});
    }

    final pageLimit = (args?["page_limit"] as num?)?.toInt() ?? 10;
    final galleryImport = args?["gallery_import"] as bool? ?? true;
    final modeName = args?["mode"] as String? ?? "full";
    final wantPdf = args?["pdf"] as bool? ?? false;

    final mode = ScannerMode.values.firstWhere(
      (m) => m.name == modeName,
      orElse: () => ScannerMode.full,
    );
    final formats = <DocumentFormat>{DocumentFormat.jpeg};
    if (wantPdf) formats.add(DocumentFormat.pdf);

    final scanner = DocumentScanner(
      options: DocumentScannerOptions(
        documentFormats: formats,
        pageLimit: pageLimit < 1 ? 1 : pageLimit,
        mode: mode,
        isGalleryImport: galleryImport,
      ),
    );

    try {
      final result = await scanner.scanDocument();
      return jsonEncode({
        "status": "ok",
        "images": result.images ?? <String>[],
        "pdf": result.pdf?.uri,
      });
    } on PlatformException catch (e) {
      final msg = e.message ?? e.code;
      final cancelled = msg.toLowerCase().contains("cancel");
      return jsonEncode({
        "status": cancelled ? "cancelled" : "error",
        "error": msg,
      });
    } catch (e) {
      return jsonEncode({"status": "error", "error": e.toString()});
    } finally {
      try {
        await scanner.close();
      } catch (_) {}
    }
  }

  @override
  void dispose() {
    control.removeInvokeMethodListener(_invokeMethod);
    super.dispose();
  }
}
