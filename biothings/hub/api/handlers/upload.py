import asyncio
import logging
import cgi
import os

from tornado.web import Application, RequestHandler, stream_request_body
from tornado import gen
from tornado.ioloop import IOLoop
from tornado.options import parse_command_line, define, options

from .base import GenericHandler
from biothings.utils.common import sizeof_fmt


@stream_request_body
class UploadHandler(GenericHandler):

    def initialize(self,upload_root,**kwargs):
        self.upload_root = upload_root

    def set_default_headers(self):
        self.set_header('Access-Control-Allow-Origin','*')
        # part of pre-flight requests
        self.set_header('Access-Control-Allow-Methods','PUT, DELETE, POST, GET, OPTIONS')
        self.set_header('Access-Control-Allow-Headers','Content-Type')

    def prepare(self):
        # sanity check + extract boundary
        ct = self.request.headers.get("Content-Type")
        if not ct:
            self.write_error(400,exc_info=[None,"No Content-Type header found",None])
        try:
            ct,boundary = ct.split(";")
        except Exception as e:
            self.write_error(400,exc_info=[None,str(e),None])
        ct = ct.strip()
        if ct != "multipart/form-data":
            self.write_error(400,exc_info=[None,"Excepting 'Content-Type: multipart/form-data', got %s" % ct,None])
        boundname,boundary = boundary.strip().split("=")
        if boundname != "boundary":
            self.write_error(400,exc_info=[None,"No boundary field found in headers",None])
        self.boundary = boundary
        cl = self.request.headers.get("Content-Length")
        if cl:
            self.contentlength = sizeof_fmt(int(cl))
        else:
            self.contentlength = "unknown size"

        self.begin = False
        self.src_name = self.request.uri.split("/")[-1]
        self.fp = None
        self.head = ""

    def parse_head(self):
        data = self.head.splitlines();
        assert "--" + self.boundary == data[0]
        length = "unknown size"
        for dat in data[1:]:
            if "Content-Disposition:".lower() in dat.lower():
                cd,cdopts = cgi.parse_header(dat)
                try:
                    self.filename = cdopts["filename"]
                except KeyError:
                    self.write_error(400,
                            exc_info=[None,"No 'filename' found in Content-Disposition",None])
            if "Content-Type:".lower() in dat.lower():
                _,ct = map(str.strip,dat.split(":"))
                if not ct == "application/octet-stream":
                    self.write_error(400,
                            exc_info=[None,"Expected 'application/octet-stream', got: %s" % ct,None])
        logging.info("Upload file '%s' (%s) for source '%s'" % (self.filename,self.contentlength,self.src_name))
        folder = os.path.join(self.upload_root,self.src_name)
        os.makedirs(folder,exist_ok=True)
        self.fp = open(os.path.join(folder,self.filename),"wb")

    @gen.coroutine
    def data_received(self, chunk):
        while True:
            if self.begin:
                endbound = b"\r\n--" + self.boundary.encode() + b"--\r\n"
                if endbound in chunk:
                    chunk = chunk.replace(endbound,b"")
                self.fp.write(chunk)
                break
            else:
                # we're in headers, assuming str conversion
                data = chunk.split(b"\r\n\r\n")
                assert len(data) >= 1
                self.head += data[0].decode()
                self.begin = True
                chunk = b"\r\n\r\n".join(data[1:])
                self.parse_head()

    def post(self,src_name):
        assert src_name == self.src_name
        self.write('ok')